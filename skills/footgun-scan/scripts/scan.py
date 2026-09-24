#!/usr/bin/env python3
"""Scan Kotlin and Compose Multiplatform changes for the shapes the kotlin-footguns traps describe.

Every detector is a pattern over source lines that points at one trap file. A hit is a shape worth a
look, not a verdict: open the trap it names and decide. Two levels:

  likely  the shape is wrong unless a specific condition holds (the trap says which)
  look    a place the trap says to inspect before trusting it

    python3 scan.py                     lines added in the working tree and index since HEAD
    python3 scan.py --base origin/main  lines added since this branch left origin/main
    python3 scan.py --all [paths...]    every line of the tracked files (a full audit, noisier)
    python3 scan.py --list              print the detectors
    python3 scan.py --self-test         run every detector against its own examples

Add --fail to exit 1 when any `likely` hit is found (for a pre-commit hook or CI).
Standard library only; needs git on PATH for everything except --self-test and --list.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_ROOT = os.path.dirname(os.path.dirname(HERE))

KOTLIN = ["*.kt", "*.kts", "*.java"]
SQL_HOSTS = ["*.kt", "*.kts", "*.java", "*.sq", "*.sql"]
BUILD = ["*.kts", "*.gradle", "*.toml"]
TEST_PATH = re.compile(r"(^|/)(test|androidTest|androidUnitTest|commonTest|jvmTest|iosTest|desktopTest)/|Test\.kt$")
SKIP_PATH = re.compile(r"(^|/)(build|\.gradle|\.idea|node_modules|generated)/")


def D(id, level, trap, pattern, message, hits, misses, files=KOTLIN, span=0, unless=None,
      requires=None, before=0, unless_before=None, skip_tests=False, check=None):
    return dict(id=id, level=level, trap=trap, pattern=re.compile(pattern) if pattern else None,
                message=message, hits=hits, misses=misses, files=files, span=span,
                unless=re.compile(unless) if unless else None,
                requires=re.compile(requires) if requires else None, before=before,
                unless_before=unless_before, skip_tests=skip_tests, check=check)


# --- custom checks -------------------------------------------------------------------------------

def call_args(text, open_paren):
    """The argument text of a call whose "(" is at text[open_paren], or None if it does not close."""
    depth = 0
    for j in range(open_paren, len(text)):
        depth += text[j] == "("
        depth -= text[j] == ")"
        if depth == 0:
            return text[open_paren + 1:j]
    return None


def gradient_to_transparent(lines, i):
    """A gradient whose own colour stops include Color.Transparent."""
    text = "\n".join(lines[i:i + 6])
    for m in re.finditer(r"Gradient\s*\(", text):
        if m.start() > len(lines[i]):
            break
        args = call_args(text, m.end() - 1)
        if not args or not re.search(r"\bColor\.Transparent\b", args):
            continue
        # Color.Transparent is black at alpha 0, so a fade whose other stops are all black is right.
        stops = colour_stops(args)
        if stops and all(c.startswith(("Color.Transparent", "Color.Black")) for c in stops):
            continue
        return True
    return False


def split_top_level(args):
    parts, depth, cur = [], 0, ""
    for ch in args:
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def colour_stops(args):
    """The colour expressions of a gradient call: a colors list, or the right side of `x to colour` pairs."""
    lst = re.search(r"\b(?:listOf|arrayOf)\s*\(", args)
    if lst:
        inner = call_args(args, lst.end() - 1) or ""
        return [p for p in split_top_level(inner) if p]
    pairs = [p.split(" to ", 1)[1].strip() for p in split_top_level(args) if " to " in p]
    return pairs


def clickable_before_clip(lines, i):
    """.clickable followed by .clip in the same modifier chain, on this line or chained below it."""
    m = re.search(r"\.(?:combinedClickable|clickable)\b", lines[i])
    if not m:
        return False
    if re.search(r"\.clip\s*\(", lines[i][m.end():]):
        return True
    for line in lines[i + 1:i + 3]:
        stripped = line.strip()
        if stripped.startswith(".clip(") or stripped.startswith(".clip ("):
            return True
        if not stripped.startswith("."):
            return False
    return False

def slide_default_offset(lines, i):
    """slideInVertically()/slideOutVertically() with no offset lambda uses half the height."""
    text = "\n".join(lines[i:i + 4])
    for m in re.finditer(r"\bslide(?:In|Out)Vertically\b\s*", text):
        if m.start() >= len(lines[i]):
            break
        rest = text[m.end():]
        if rest.startswith("{"):
            continue  # trailing lambda is the offset
        if not rest.startswith("("):
            continue  # a reference, not a call
        depth, j = 0, 0
        for j, ch in enumerate(rest):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0:
                break
        args, after = rest[1:j], rest[j + 1:]
        if "OffsetY" in args or "{" in args or after.lstrip().startswith("{"):
            continue
        return True
    return False


def callback_writes_twice(lines, i):
    """A listener callback that writes one state holder unconditionally and again elsewhere.

    Writes confined to separate branches (if/else, when) are one write per event and pass.
    """
    if not re.search(r"\boverride\s+fun\s+on[A-Z]\w*\s*\(", lines[i]):
        return False
    depth, started = 0, False
    top, anywhere = {}, {}
    for line in lines[i:i + 60]:
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', line.split("//")[0])
        if started:
            for name in re.findall(r"\b(_?\w+)\.value\s*=(?!=)|\b(_?\w+)\.update\s*\{", code):
                name = name[0] or name[1]
                anywhere[name] = anywhere.get(name, 0) + 1
                if depth == 1:
                    top[name] = top.get(name, 0) + 1
        for ch in code:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
        if started and depth <= 0:
            break
    return any(anywhere.get(name, 0) >= 2 for name in top)


# --- detectors -------------------------------------------------------------------------------------

DETECTORS = [
    # data layer
    D("not-in-subquery-unguarded", "look", "data-layer-footguns/sql-not-in-nullable-trap",
      r"(?i)\bNOT\s+IN\s*\(\s*SELECT\b",
      "NOT IN over a subquery: if that column is nullable, one NULL makes it match nothing; guard with IS NOT NULL or note that it is NOT NULL",
      hits=['@Query("DELETE FROM playlist WHERE id NOT IN (SELECT remotePlaylistId FROM local_playlist)")'],
      misses=['@Query("DELETE FROM p WHERE id NOT IN (SELECT rid FROM l WHERE rid IS NOT NULL)")'],
      files=SQL_HOSTS, span=3, unless=r"(?i)\bNOT\s+NULL\b"),
    D("like-pattern-concatenated", "likely", "data-layer-footguns/like-wildcard-escaping-ids",
      r"(?i)\bLIKE\s+'%'\s*\|\|",
      "LIKE built from a value: `_` and `%` inside the value are wildcards unless escaped with an ESCAPE clause",
      hits=["WHERE json LIKE '%' || :id || '%'"],
      misses=["WHERE json LIKE '%' || :id || '%' ESCAPE '\\\\'", "WHERE name LIKE 'abc%'"],
      files=SQL_HOSTS, span=2, unless=r"(?i)\bESCAPE\b"),
    D("like-pattern-interpolated", "look", "data-layer-footguns/like-wildcard-escaping-ids",
      r'"%\$\{?[\w.]+\}?%"',
      "a LIKE pattern built from a value: escape `_` and `%` in it and pass an ESCAPE clause",
      hits=['dao.search("%$query%")', 'dao.find("%${item.id}%")'],
      misses=['println("100%")']),
    D("vacuum-through-raw-query", "likely", "data-layer-footguns/room-rawquery-readonly-vacuum",
      r'(?i)\b(RoomRawQuery|SimpleSQLiteQuery)\s*\(\s*"\s*VACUUM',
      "a raw-query DAO method runs on a read-only connection, so VACUUM fails there; run it on a writer connection from the database class",
      hits=['dao.raw(RoomRawQuery("VACUUM"))'],
      misses=['dao.raw(RoomRawQuery("PRAGMA wal_checkpoint(FULL)"))']),
    D("sql-localtime", "likely", "data-layer-footguns/bucket-local-time-in-code-not-in-sql",
      r"(?i)'localtime'",
      "SQLite's 'localtime' uses the process time zone; bucket local hours and days in code from one raw scan",
      hits=["SELECT strftime('%H', ts / 1000, 'unixepoch', 'localtime') AS hour"],
      misses=["SELECT strftime('%s', 'now')"], files=SQL_HOSTS),
    D("sql-strftime-bucket", "look", "data-layer-footguns/bucket-local-time-in-code-not-in-sql",
      r"(?i)\bstrftime\s*\(\s*'%[HdjmwWY]",
      "bucketing by hour or day in SQL answers in UTC or the process zone, not the user's; bucket in code",
      hits=["GROUP BY strftime('%H', playedAt / 1000, 'unixepoch')"],
      misses=["SELECT strftime('%s', 'now')"], files=SQL_HOSTS),
    D("migration-sql-interpolated", "likely", "data-layer-footguns/room-migrations-at-scale",
      r'\bexecSQL\s*\(\s*"[^"\n]*(\$\{?\w|"\s*\+\s*[A-Za-z_])',
      "values spliced into execSQL are concatenated, not bound: a quote in user data ends the statement mid-migration",
      hits=['db.execSQL("INSERT INTO t (a) VALUES (\'${row.songId}\')")',
            'db.execSQL("UPDATE t SET name = \'" + name + "\'")'],
      misses=['db.execSQL("DROP TABLE IF EXISTS `format`")',
              'db.execSQL("CREATE TRIGGER x " +\n    "AFTER DELETE ON t BEGIN END;")'],
      span=1),
    D("migration-graph-changed", "look", "data-layer-footguns/room-migrations-at-scale",
      r"\bAutoMigration\s*\(|\bMigration\s*\(\s*\d+\s*,\s*\d+\s*\)",
      "a migration edge changed: run the trap's reachability check so every shipped version still reaches the head",
      hits=["AutoMigration(from = 23, to = 24),", "object : Migration(5, 6) {"],
      misses=["val migration = createMigration()"]),

    # reactive state
    D("job-relaunched-without-cancel", "look", "state-and-background-footguns/named-job-lifecycle-discipline",
      r"^\s*(\w*[jJ]ob)\s*=\s*[\w.()]*\blaunch\b",
      "a job field relaunched without cancelling the previous one leaves the old coroutine running",
      hits=["fun start() {\n    progressJob = scope.launch { tick() }\n}"],
      misses=["fun start() {\n    progressJob?.cancel()\n    progressJob = scope.launch { tick() }\n}"],
      before=3, unless_before=r"\b{1}\??\.cancel(AndJoin)?\s*\("),
    D("run-blocking", "look", "state-and-background-footguns/compose-multiplatform-viewmodel-base",
      r"\brunBlocking\s*[({]",
      "runBlocking on a path that can reach the main thread stalls the UI; tolerable only off-main or once at startup",
      hits=["val s = runBlocking { getString(Res.string.title) }"],
      misses=["val s = getString(Res.string.title)"], skip_tests=True),
    D("callback-writes-state-twice", "look", "state-and-background-footguns/stateflow-conflation-inverts-state",
      None,
      "this callback writes the same state holder more than once per event; with a conflated StateFlow the last write wins",
      hits=["override fun onIsLoadingChanged(isLoading: Boolean) {\n    _state.value = Loading\n"
            "    if (ready) _state.value = Ready\n}"],
      misses=["override fun onIsLoadingChanged(isLoading: Boolean) {\n"
              "    _state.value = if (isLoading) Loading else Ready\n}",
              "override fun onIsLoadingChanged(isLoading: Boolean) {\n    if (isLoading) {\n"
              "        start()\n        _state.value = Loading\n    } else {\n        stop()\n"
              "        _state.value = Ready\n    }\n}"],
      check=callback_writes_twice),

    # Compose visuals
    D("slide-default-half-height", "likely", "compose-visuals-footguns/slide-transition-defaults-to-half-a-height",
      None,
      "a vertical slide with no offset starts at half the element's height and reads as a pop; pass the full height",
      hits=["enter = slideInVertically() + fadeIn(),", "exit = slideOutVertically(tween(200))"],
      misses=["enter = slideInVertically { it } + fadeIn()",
              "enter = slideInVertically(initialOffsetY = { it })",
              "enter = slideInVertically(tween(300)) { it }"],
      check=slide_default_offset),
    D("gradient-to-transparent", "likely", "compose-visuals-footguns/smooth-scrim-gradient",
      None,
      "Color.Transparent is black at alpha 0, so a fade to a colour passes through grey; use color.copy(alpha = 0f)",
      hits=["Brush.verticalGradient(listOf(Color.Transparent, background))",
            "Brush.verticalGradient(0f to Color.Transparent, 0.6f to ground)",
            "Brush.verticalGradient(\n    colors = listOf(Color.Transparent, bg)\n)"],
      misses=["Brush.verticalGradient(listOf(bg.copy(alpha = 0f), bg))",
              "Brush.verticalGradient(\n    colors = listOf(Color.Transparent, Color.Black),\n"
              "    startY = size.height - 200.dp.toPx(),\n    endY = size.height,\n)",
              "val b = Brush.verticalGradient(listOf(a, bg))\nBox(Modifier.background(Color.Transparent))",
              "Brush.verticalGradient(colors = listOf(Color.Transparent, Color.Black))",
              "Brush.verticalGradient(0f to Color.Black.copy(alpha = 0.55f), 1f to Color.Transparent)"],
      check=gradient_to_transparent),
    D("clickable-before-clip", "likely", "compose-visuals-footguns/touch-indication-bounds-and-alpha",
      None,
      "a clip bounds only what comes after it: .clickable before .clip ripples a rectangle past the rounded corners",
      hits=["Modifier.clickable { open() }.clip(RoundedCornerShape(12.dp))",
            "Modifier\n    .clickable { open() }\n    .clip(shape)"],
      misses=["Modifier.clip(shape).clickable { open() }",
              "Row(Modifier.clickable { open() }) {\n    Box(Modifier.clip(shape))\n}"],
      check=clickable_before_clip),
    D("delta-divides-by-baseline", "look", "compose-visuals-footguns/delta-absent-not-infinite",
      r"\(\s*[\w.]+\s*-\s*[\w.]+\s*\)\s*\*\s*100(?:\.0)?[fFdDL]?\s*/\s*[\w.]+",
      "a change against a zero or missing baseline must render as absence, not +100% or infinity; return null there",
      hits=["val pct = ((now - before) * 100.0 / before).toInt()"],
      misses=["val pct = part * 100 / total"]),

    # Compose screens
    D("pointer-input-unit", "look", "compose-screens-footguns/swipe-action-list-row",
      r"\.pointerInput\s*\(\s*Unit\s*\)",
      "pointerInput(Unit) keeps the state captured at first composition; key it on any flag the gesture reads",
      hits=["Modifier.pointerInput(Unit) { detectTapGestures { if (selecting) toggle() } }"],
      misses=["Modifier.pointerInput(selectionMode) { detectTapGestures { } }"]),
    D("zeroed-bar-insets", "look", "compose-screens-footguns/stacked-bars-double-consume-window-insets",
      r"\bwindowInsets\s*=\s*WindowInsets\s*\(\s*0",
      "zeroing a bar's insets is right only where its container already consumed them; overlay call sites need the default",
      hits=["TopAppBar(title = { }, windowInsets = WindowInsets(0, 0, 0, 0))"],
      misses=["TopAppBar(title = { }, windowInsets = TopAppBarDefaults.windowInsets)"]),
    D("slider-value-range", "look", "compose-screens-footguns/control-range-must-cover-stored-values",
      r"\bvalueRange\s*=",
      "a stored or imported value outside valueRange parks the thumb and the first touch rewrites it; size the range from real data",
      hits=["Slider(value = gain, onValueChange = { }, valueRange = -12f..12f)"],
      misses=["Slider(value = v, onValueChange = { })"]),

    # KMP structure and language
    D("resource-format-flags", "likely", "kmp-architecture-footguns/string-resource-format-limits",
      r"%(?:\d+\$)?(?:[-#+0,(]+\d*|\d+|\d*\.\d+)[a-zA-Z]|%%",
      "the multiplatform resource formatter substitutes only plain %1$s / %1$d: flags, width, precision and %% reach the screen as text",
      hits=['<string name="peak">%1$02d:00</string>', '<string name="c">%1$d%% done</string>',
            '<string name="r">%.1f stars</string>'],
      misses=['<string name="a">%1$s of %2$s</string>', '<string name="b">%1$d songs</string>',
              '<string name="p">100% done</string>'],
      files=["*composeResources/*strings*.xml"]),
    D("english-month-names", "look", "kmp-architecture-footguns/string-resource-format-limits",
      r"\.month\.name\b|\bMonth\.[A-Z]+\.name\b|\.dayOfWeek\.name\b",
      "kotlinx-datetime month and weekday names are English constants, not locale lookups",
      hits=["Text(date.month.name.lowercase())"], misses=["Text(date.monthNumber.toString())"]),
    D("empty-actual", "look", "engineering-method-footguns/noop-actual-not-platform-limit",
      r"\bactual\s+fun\s+[^\n{=]*\)\s*(?::\s*[\w.<>?, ]+)?\s*(?:\{\s*\}|=\s*(?:Unit|this|null|false|emptyList\(\))\s*$)",
      "an empty actual reads as 'this platform cannot', but usually means nobody wrote it yet",
      hits=["actual fun Modifier.frostedSurface(source: SurfaceSource): Modifier = this", "actual fun keepScreenOn() {}"],
      misses=['actual fun platformName(): String = "Desktop"', "actual fun keepScreenOn() {\n    window.on()\n}"]),
    D("koin-annotations", "look", "kmp-architecture-footguns/koin-viewmodel-scoping-traps",
      r"^\s*@(?:Single|Factory|KoinViewModel|ComponentScan)\b",
      "koin-annotations do nothing unless the KSP-generated module is loaded; confirm it is, or the binding is silently missing",
      hits=["@Single\nclass Repo"], misses=["@Singleton\nclass Repo", "val single = 1"]),

    # remote APIs
    D("unbounded-retry", "likely", "remote-api-footguns/retry-needs-backoff-and-cap",
      r"(?<!Result)\.retry\s*\(\s*\)|\.retry\s*\(\s*(?:Long|Int)\.MAX_VALUE|\.retryWhen\s*\{\s*\w+\s*,\s*\w+\s*->\s*true\s*\}",
      "an unbounded retry with no backoff hammers the network and battery; cap it, back off, and refuse to retry some errors",
      hits=["flow.retry()", "flow.retryWhen { _, _ -> true }", "flow.retry(Long.MAX_VALUE)"],
      misses=["flow.retry(3) { it is IOException }", "return Result.retry()"]),
    D("reconnect-loop-without-delay", "look", "remote-api-footguns/retry-needs-backoff-and-cap",
      r"\bwhile\s*\(\s*(?:true|isActive)\s*\)",
      "a reconnect loop with no delay spins on every failure; add exponential backoff, a ceiling and a lifecycle gate",
      hits=["while (true) {\n    try { socket.connect() } catch (e: IOException) { }\n}"],
      misses=["while (true) {\n    try { socket.connect() } catch (e: IOException) { delay(backoff) }\n}",
              "while (true) {\n    val line = reader.readLine() ?: break\n}"],
      span=12, unless=r"\bdelay\s*\(|(?i:backoff)",
      requires=r"\b(?:re)?[cC]onnect\s*\(|\bretry\b|\blogin\s*\(|\bauthenticate\s*\(", skip_tests=True),

    # desktop and build
    D("ls-environment", "look", "desktop-and-build-footguns/macos-lsenvironment-path-pin",
      r"\bLSEnvironment\b",
      "an LSEnvironment dictionary pins PATH to the bare system directories for every process the app spawns",
      hits=["<key>LSEnvironment</key>"], misses=["<key>LSMinimumSystemVersion</key>"],
      files=["*.plist", "*.kts", "*.gradle", "*.conf", "*.xml", "*.json", "*.kt", "*.toml"]),
    D("bare-command-spawn", "look", "desktop-and-build-footguns/macos-lsenvironment-path-pin",
      r'\bProcessBuilder\s*\(\s*(?:listOf\s*\(\s*|arrayOf\s*\(\s*)?"[A-Za-z][\w.+-]*"'
      r'|\bRuntime\.getRuntime\(\)\.exec\s*\(\s*(?:arrayOf\s*\(\s*)?"[A-Za-z]',
      "a bare command name resolves through PATH, which a Finder or Dock launch does not share with your terminal",
      hits=['ProcessBuilder("ffmpeg", "-i", input)', 'Runtime.getRuntime().exec("open " + url)'],
      misses=['ProcessBuilder("/usr/bin/open", url)', "ProcessBuilder(command)"]),
    D("wmic", "look", "desktop-and-build-footguns/windows-vm-detection-post-wmic",
      r"(?i)\bwmic\b",
      "wmic is gone from current Windows 11; query CIM through PowerShell first and keep wmic only as a fallback",
      hits=['ProcessBuilder("wmic", "computersystem", "get", "model")'], misses=['ProcessBuilder("powershell")'],
      files=KOTLIN + ["*.ps1", "*.bat", "*.cmd"]),
    D("native-load", "look", "desktop-and-build-footguns/jna-native-binding-traps",
      r"\bNative\.load\s*\(|\bSystem\.load(?:Library)?\s*\(",
      "log the path the native library actually resolved from, or a broken bundle can pass as working",
      hits=['val lib = Native.load("mpv", MpvLibrary::class.java)'], misses=["val lib = loadConfig()"]),
    D("strict-version", "look", "desktop-and-build-footguns/transitive-version-pinning",
      r"\bstrictly\s*\(|\bstrictly\s*=",
      "a strictly constraint overrides BOM alignment for everything downstream; confirm the runtime path expects this version",
      hits=['version { strictly("1.7.3") }', 'foo = { module = "a:b", version = { strictly = "1.0" } }'],
      misses=['implementation("a:b:1.0")'], files=BUILD),

    # media playback
    D("player-handles-audio-focus", "look", "media-playback-footguns/audio-focus-multiplayer",
      r"\.setAudioAttributes\s*\([^)]*,\s*(?:/\*[^*]*\*/\s*)?true\s*\)",
      "with more than one player, exactly one app-level owner should hold audio focus; per-player handling makes them fight",
      hits=["ExoPlayer.Builder(ctx).setAudioAttributes(attrs, true)",
            "builder.setAudioAttributes(attrs, /* handleAudioFocus = */ true)"],
      misses=["builder.setAudioAttributes(attrs, /* handleAudioFocus = */ false)"]),
    D("loudness-enhancer", "look", "media-playback-footguns/per-track-loudness-normalization",
      r"\bLoudnessEnhancer\s*\(",
      "an audio effect is bound to one audio session and dies with it; recreate it per track or player",
      hits=["enhancer = LoudnessEnhancer(player.audioSessionId)"], misses=["enhancer?.release()"]),
    D("forwarding-player", "look", "media-playback-footguns/fgs-state-ended-trap",
      r":\s*ForwardingPlayer\s*\(",
      "if the delegate is swapped between items, suppress STATE_ENDED during the swap or the service drops foreground",
      hits=["class SwappablePlayer(p: Player) : ForwardingPlayer(p) {"], misses=["val p: Player = exo"]),
]


# --- scanning --------------------------------------------------------------------------------------

def applies(det, path):
    if SKIP_PATH.search(path):
        return False
    if det["skip_tests"] and TEST_PATH.search(path):
        return False
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(os.path.basename(path), g) for g in det["files"])


COMMENT = ("//", "/*", "*", "#", "<!--")


def match_at(det, lines, i):
    if lines[i].lstrip().startswith(COMMENT):
        return False
    if det["check"]:
        return det["check"](lines, i)
    text = "\n".join(lines[i:i + det["span"] + 1])
    m = det["pattern"].search(text)
    if not m or m.start() >= len(lines[i]) + 1:
        return False
    window = text
    if det["unless"] and det["unless"].search(window):
        return False
    if det["requires"] and not det["requires"].search(window):
        return False
    if det["unless_before"]:
        pat = det["unless_before"]
        for n, g in enumerate(m.groups() or (), start=1):
            pat = pat.replace("{%d}" % n, re.escape(g or ""))
        prior = "\n".join(lines[max(0, i - det["before"]):i])
        if re.search(pat, prior):
            return False
    return True


def scan_file(path, lines, line_numbers):
    """line_numbers: 1-based lines to test, or None for all."""
    found = []
    targets = range(len(lines)) if line_numbers is None else [n - 1 for n in sorted(line_numbers) if 0 < n <= len(lines)]
    for det in DETECTORS:
        if not applies(det, path):
            continue
        for i in targets:
            if match_at(det, lines, i):
                found.append((path, i + 1, det))
    return found


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def added_lines(base):
    """{path: set(line numbers)} for lines added relative to base (a commit), plus untracked files."""
    out = git("diff", "--unified=0", "--no-color", "--no-ext-diff", base)
    result, path, line = {}, None, 0
    for raw in out.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            result.setdefault(path, set()).add(line)
            line += 1
    for p in git("ls-files", "--others", "--exclude-standard").splitlines():
        result[p] = None
    return result


def read_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().split("\n")
    except OSError:
        return None


def trap_path(trap):
    area, name = trap.split("/")
    p = os.path.join(SKILLS_ROOT, area, "references", name + ".md")
    return p if os.path.exists(p) else f"{area}/references/{name}.md"


def self_test():
    failures = 0
    for det in DETECTORS:
        for sample, want in [(s, True) for s in det["hits"]] + [(s, False) for s in det["misses"]]:
            lines = sample.split("\n")
            got = any(match_at(det, lines, i) for i in range(len(lines)))
            if got != want:
                failures += 1
                print(f"FAIL {det['id']}: expected {'a hit' if want else 'no hit'} on {sample!r}")
        area, name = det["trap"].split("/")
        if not os.path.exists(os.path.join(SKILLS_ROOT, area, "references", name + ".md")):
            failures += 1
            print(f"FAIL {det['id']}: trap {det['trap']} not found under {SKILLS_ROOT}")
    print(f"{len(DETECTORS)} detectors, {failures} failures")
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="limit the scan to these files or directories")
    ap.add_argument("--base", help="scan lines added since the merge base with this ref")
    ap.add_argument("--all", action="store_true", help="scan every line of the tracked files")
    ap.add_argument("--fail", action="store_true", help="exit 1 if any `likely` hit is found")
    ap.add_argument("--list", action="store_true", help="print the detectors and exit")
    ap.add_argument("--self-test", action="store_true", help="run each detector against its examples")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.list:
        for d in DETECTORS:
            print(f"{d['id']:32} {d['level']:6} {d['trap']}")
        return 0

    try:
        top = git("rev-parse", "--show-toplevel").strip()
        roots = [os.path.relpath(os.path.abspath(p), top) for p in args.paths]
        os.chdir(top)
        if args.all:
            files = {p: None for p in git("ls-files").splitlines()}
        else:
            base = git("merge-base", args.base, "HEAD").strip() if args.base else "HEAD"
            files = added_lines(base)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"footgun-scan: git failed: {e}", file=sys.stderr)
        return 2

    if roots:
        files = {p: v for p, v in files.items()
                 if any(r == "." or p == r or p.startswith(r + "/") for r in roots)}

    hits, scanned = [], 0
    for path, numbers in sorted(files.items()):
        if not any(applies(d, path) for d in DETECTORS):
            continue
        lines = read_lines(path)
        if lines is None:
            continue
        scanned += 1
        hits += scan_file(path, lines, numbers)

    scope = "all tracked files" if args.all else f"lines added since {args.base or 'HEAD'}"
    print(f"footgun-scan: {len(hits)} hit(s) in {len({h[0] for h in hits})} file(s); "
          f"{scanned} file(s) scanned ({scope})")
    groups = {}
    for path, line, det in hits:
        groups.setdefault((path, det["id"]), (det, []))[1].append(line)
    order = sorted(groups.items(), key=lambda g: (g[1][0]["level"] != "likely", g[0][0], min(g[1][1])))
    for (path, _), (det, lines) in order:
        lines.sort()
        more = ""
        if len(lines) > 1:
            shown = ", ".join(str(n) for n in lines[1:9])
            more = f"  (+{len(lines) - 1} more here: {shown}{', ...' if len(lines) > 9 else ''})"
        print(f"\n{path}:{lines[0]}  {det['level']}  {det['id']}{more}\n"
              f"    {det['message']}\n    -> {trap_path(det['trap'])}")
    return 1 if args.fail and any(h[2]["level"] == "likely" for h in hits) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # output piped into head and closed early
        sys.stderr.close()
        sys.exit(0)
