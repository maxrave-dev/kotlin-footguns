---
name: windows-vm-detection-post-wmic
description: Detect that a desktop app is running inside a virtual machine on Windows after the classic command-line management query tool was removed in Windows 11 — query the management layer through PowerShell, probe both the manufacturer and the model field, and pick the fail direction deliberately; reach for it when a transparent or undecorated window renders nothing on a VM while the process keeps running, or when a detection probe that worked for years suddenly reports empty on every modern host.
---

# Detecting a virtual machine on Windows

Some window features do not survive a VM's graphics driver. A transparent, undecorated window is
the usual casualty: it never paints, the process stays alive, and the user sees nothing at all.
The fix is to detect the VM and fall back to a normal decorated window — which makes the *detection*
the load-bearing part.

The system fields that carry a hypervisor's brand live in the computer-system record of Windows'
management layer. Read them, match against known vendor strings.

```kotlin
// adapted — extracted from the window-construction path, inside a `remember { }`
// Guard first: both probes below are Windows-only commands. Without this the
// app spawns a doomed subprocess on every macOS and Linux launch.
val osName = System.getProperty("os.name", "")
if (!osName.contains("Windows", ignoreCase = true)) return@remember false

val probes = listOf(
    listOf(
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance Win32_ComputerSystem | " +
            "Select-Object Manufacturer,Model | " +
            "Format-List | Out-String).Trim()",
    ),
    listOf("wmic", "computersystem", "get", "manufacturer,model"), // older hosts only
)
val sysInfo = probes.asSequence()
    .mapNotNull { cmd ->
        runCatching {
            val p = ProcessBuilder(cmd).redirectErrorStream(true).start()
            val out = p.inputStream.bufferedReader().readText()
            if (p.waitFor() == 0 && out.isNotBlank()) out else null
        }.getOrNull()
    }.firstOrNull().orEmpty()

val vmTokens = listOf("Parallels", "VirtualBox", "VMware", "QEMU", "KVM", "Xen", "Hyper-V")
val isVM = vmTokens.any { sysInfo.contains(it, ignoreCase = true) } ||
    System.getProperty("app.window.no-transparent", "false").toBooleanStrictOrNull() == true
```

Then: `Window(undecorated = !isVM, transparent = !isVM, …)`.

## Traps

**The classic command-line query tool is gone.** It was deprecated in Windows 10 21H1 and is not
installed by default on **Windows 11** — a version-scoped fact, so keep it as the *fallback* probe
rather than deleting it, since older hosts still have it and may not have a usable PowerShell path.
On a modern host the old tool answers "not recognized", the probe reads back empty, and the code
concludes "real hardware". This is exactly how a detection that shipped working degrades into a
detection that has silently never run.

**Probe BOTH the manufacturer and the model field.** Which one carries the brand differs per
hypervisor and per architecture — one product puts its company name in the manufacturer field and
its product name in the model field; another puts a company name you would never guess in the
manufacturer field and the recognisable brand only in the model. Reading one field is how a
detection passes on your laptop's VM and fails on a user's.

**Decide the fail direction on purpose, and know what it costs.** Detection failure here resolves
to "not a VM", which keeps the enhanced window. That is the right default for a hardened or
unusual host that simply refuses to answer — it should not lose features for being quiet. But it
also means *a broken probe is indistinguishable from real hardware*, and its symptom is the worst
one available: an invisible window. If your fallback path is the cheap one instead, invert it.
Either way, write down which way it fails and why.

**Ship a manual override.** No token list is exhaustive and no probe is guaranteed to answer. A
system property (or an environment variable, or a settings toggle) that forces the fallback path
turns "unusable, file a bug and wait for a release" into "add one flag". Note that the override in
the excerpt only forces the *safe* direction — there is deliberately no way to force transparency
on, because that is the state that renders nothing.

**Run the probe once and remember it.** It spawns a process. Doing that on every recomposition, or
on every window resize, is a visible stall. Compute it once at window construction.

**Redirect the error stream into the output you read, and require a zero exit *and* non-blank
output.** A probe that writes its complaint to standard error and exits zero otherwise looks like a
successful empty answer.

**Do not extend the token list by guessing.** Vendor strings are not documented as an API and
change between product generations.

## Verifying it

The token list is data, not knowledge — regenerate it rather than trusting this file. On any host
you care about, run the query itself and read what it prints:

```powershell
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | Format-List
```

Two checks that catch the failure this skill exists for:

1. **Prove the probe ran.** Log the raw captured text, not just the boolean. An empty string with
   `isVM = false` and a real string with `isVM = false` are entirely different situations and the
   boolean cannot tell them apart.
2. **Prove the fallback works on a real guest**, not on a resized window on your own machine. The
   render failure comes from the guest's graphics driver; nothing on the host reproduces it.
