---
name: windows-msix-offline-installer
description: Ship a self-signed MSIX (the modern Windows application package format) that end users can actually install without a hosted update site — bundle an install script plus the signing certificate beside the package, script the trust-then-sideload steps, and keep the signing key stable across releases; reach for it when double-clicking the packager's output fails, when its wrapper installer dies fetching a URL that returns 404, or when a new build refuses to install over the previous one.
---

# Offline installer for a self-signed Windows package

The packager this was mined from emits, for Windows, three things: the package itself, a small
executable wrapper, and an app-installer manifest. The last two are **online** artifacts: each
fetches URLs under the site base URL you configured, typically a "latest release" path. Before that release exists — every pre-release build, every artifact downloaded from a CI
run — those URLs return 404 and both fail. The raw package alone cannot be double-clicked either,
because the machine does not trust the self-signed certificate that produced it.

What users can install is a **zip of three files**:

```
<App>-Windows-installer.zip
├── install.bat          elevate to administrator → import cert → sideload package
├── app.crt              the self-signed code-signing certificate
└── app-<version>.x64.msix
```

CI assembles it from the packager's output directory:

```yaml
# adapted
- name: Bundle Windows offline installer
  run: |
    set -euo pipefail
    if [ ! -f output/app.crt ]; then
      echo "::error::output/app.crt missing — signing must have failed"
      exit 1
    fi
    msix=$(ls output/app-*.x64.msix 2>/dev/null | head -1)
    [ -n "$msix" ] || { echo "::error::No x64 .msix in output/"; exit 1; }
    stage="$(mktemp -d)"
    cp scripts/windows/install.bat output/app.crt "$msix" "$stage/"
    ( cd "$stage" && zip -q -j "$GITHUB_WORKSPACE/installers/App-Windows-installer.zip" \
        install.bat app.crt "$(basename "$msix")" )
```

## Traps

**The certificate is an output you have to check for.** The signing step can fail while the rest of
the build succeeds; the certificate then never lands in the output directory and the zip ships with
two of three files. Assert its presence and fail the job — that check is the entire early-warning
system.

**Import the certificate to the machine's trusted-people store, not the current user's.** That is
the store the shipped script targets, and `certutil -addstore -f "TrustedPeople" app.crt` is
idempotent, so re-running the installer is safe. (The likely reason machine-wide is required —
the sideload runs elevated — is worth verifying against your own elevation flow rather than
taking on faith.)

**Self-elevate rather than telling users to right-click.** Both the certificate import and the
sideload need administrator rights. Re-launching the script through the elevation verb keeps the
whole thing a double-click:

```bat
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
```

**Keep the signing key stable across releases.** The package's publisher identity is derived from
the signing certificate. Regenerate the key and every existing installation becomes a *different*
application: the in-place update path fails, and the only way forward is removing the old package
first — which is a data-loss risk you have handed to your users. Pin the key as a CI secret and
never rotate it casually.

**Install with the force-update flag, and keep a remove-then-install fallback.** Without it, a
rebuild at an identical version number will not overwrite the existing install, so testers have to
uninstall by hand between builds. And even with it, an install can still fail — a changed publisher
is the common cause — so catch it and fall back:

```bat
:: adapted — the quoted command stays on ONE physical line: cmd stops honouring the ^
:: continuation once it is inside a double-quoted string, so a line-wrapped copy of this
:: simply does not run. Only the ^ directly after -Command, outside the quotes, is legal.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "try { Add-AppxPackage -Path '%MSIX%' -ForceApplicationShutdown -ForceUpdateFromAnyVersion -ErrorAction Stop; exit 0 } catch { Write-Host $_; exit 1 }"
if %errorlevel% neq 0 goto :recovery
```

The inner `exit 0` / `exit 1` pair is load-bearing: it is what makes `%errorlevel%` reflect the
PowerShell outcome, so the recovery branch — the remove-then-reinstall fallback and the printed
recovery steps two traps below — actually fires.

**Glob for the package, do not hardcode its version.** The filename carries the version; a script
that names it needs editing every release. `for %%f in ("%~dp0app-*.msix") do set "MSIX=%%f"`
survives bumps — and, if you ever ship one architecture per bundle, it also removes the need for
host-architecture detection inside the script.

**`cd /d "%~dp0"` first, and reference every bundled file through `%~dp0`.** The script runs from
whatever directory the elevation started it in, which is not the folder the user unzipped.

**Print the recovery steps on failure instead of just an error code.** The two failures users
actually hit are sideloading being disabled in the developer settings and a machine that needs a
restart before the newly trusted certificate takes effect. Both are one sentence each, and neither
is discoverable from a non-zero exit.

**Say how to uninstall.** A sideloaded package does not appear where users look for installers;
tell them it is under installed apps.

## Verifying it

- Unzip the bundle on a machine that has **never** built the app and double-click the script. A
  developer machine already trusts the certificate, so it cannot reproduce the untrusted case.
- Confirm the architecture the app actually started as, in the task manager's details view — a
  package can install and run under emulation without saying so anywhere.
- Test the *upgrade* path, not just the clean install: install the previous release, then run the
  new bundle over it. That is the path a stable signing key protects and the one nobody tests.
