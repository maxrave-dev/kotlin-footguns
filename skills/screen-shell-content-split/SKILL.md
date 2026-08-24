---
name: screen-shell-content-split
description: Split one screen into a shell that owns every cross-look concern and a content layer that only renders, connected by two holders — a state snapshot and an actions bag — so adding a second look costs one branch instead of a parameter-list edit; covers why the holders are stable-but-not-immutable, what must stay in the shell, and what must not. Use when a screen has grown a second visual style, when a style switch resets the scroll position or the artwork page, when adding a look means editing a fifty-argument signature, or when a "shared" helper starts needing a per-style `if`.
---

# One screen, several interchangeable looks

The shell collects state, runs the effects, hosts the sheets and dialogs, and owns the gesture state
machines. A content composable is handed a snapshot and a set of callbacks and does nothing but
render. Adding a look is then a new file plus one branch.

```kotlin
// adapted
val state = PlayerContentState(screenData = …, controllerState = …, artworkPagerState = …, …)
val actions = PlayerContentActions(onUIEvent = { vm.onUIEvent(it) }, onShowQueue = { showQueue = true }, …)
when (style) {
    STYLE_TONAL -> PlayerContentTonal(state = state, actions = actions)
    else -> PlayerContentClassic(state = state, actions = actions)
}
```

## Traps

**Two holders, not one, and not a parameter list.** Reads and writes have different lifetimes: the
snapshot is rebuilt on every recomposition, the callback bag is a set of closures over the shell's
own `var`s. Fusing them makes every callback a reason to rebuild the snapshot. Flattening them into
arguments makes a new look a diff on every existing call site — which is precisely the cost the split
exists to remove.

**Mark them `@Stable`, never `@Immutable`.** `@Immutable` is a promise that every property is
observably constant, and the holder deliberately carries live handles beside its snapshots — a pager
state, animatables, a scroll state, a flow. The runtime believes `@Immutable` and will skip
recomposition it should have run. `@Stable` says the right thing: the reference is stable, changes
are notified through the snapshot system.

**Build both holders unconditionally, above the branch.** Constructing them inside a branch ties
every remembered handle they carry to that branch's lifetime, so a style switch drops the scroll
position, the artwork page and the in-flight colour animation. Built above, the same pager and scroll
state are handed to whichever look renders and a switch is visually seamless.

**The branch needs no `key()` and no navigation destination.** Different call sites already get
different composition groups, so the two looks do not share slot state; and routing a *presentation*
choice through the back stack makes a settings toggle push a screen. A plain `when` with an `else`
default is the whole mechanism — and the `else` is what makes an unknown persisted value fall back to
the original look instead of rendering nothing.

**Decide per concern whether it is the shell's, and write the list down.** The shell owns what must
behave identically no matter which look renders: view-model collection, palette animation, the
artwork-pager two-way sync (`nowplaying-pager-no-feedback-loop`), auto-hide timers, and every sheet
and dialog. If two looks would disagree about it, it is not the shell's.

**Layout maths and animation curves are exactly what must NOT be hoisted.** They read like shared
code and are not: see `variant-layout-math-stays-in-the-variant` for the measurement block that
diverged, and `hoist-the-flag-not-the-animation` for the shared tween that had to become two.

**A shared *state* object does not make the *composable* shared.** The artwork pager's state and all
of its synchronisation effects live in the shell (`nowplaying-pager-no-feedback-loop`), but the pager
itself is emitted by each look — so its parameters are duplicated per look and drift silently. Here
`userScrollEnabled = !isRepeatOne && queue.isNotEmpty()` and the off-screen page budget appear once
in each content file, and a guard fixed in one is still broken in the other. Either keep them
identical on purpose, or move the expression onto the state holder so there is one copy.

**A field one look ignores is normal — and a written claim that it is ignored is not evidence.**
The shell publishes a superset; each look reads what it needs. Deleting a field because one style
does not read it breaks the other. Equally, a changelog entry listing three "intentionally unused"
fields was wrong about two of them (since corrected) — a written claim that a field is unused is not
evidence; grep for the consumers.

**Keep the holders free of the view model, and a look becomes testable.** They are plain classes of
values and lambdas, so a preview or a test constructs one with fakes and renders a look with no
container, no player and no navigation. The moment a holder carries the view model itself — or a
navigation controller — that property is gone and the split has bought only file size.

**Genuinely shared leaf helpers belong beside the holders, not in either look.** A text-normalising
extension used by both styles lives in the holder file, `internal`, so neither look imports the
other. The moment a helper needs a per-style `if`, it was never shared: copy it.

## Verifying it

1. Both holders exist and are `@Stable`, and nothing in the pair is `@Immutable`:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B1 "^class .*ContentState(\|^class .*ContentActions(" .
   ```

2. Every live handle the state holder carries — this is the list that forbids `@Immutable`:

   ```bash
   grep -nE "val .*: (PagerState|ScrollState|Animatable|StateFlow)" \
     $(grep -rl --include='*.kt' --exclude-dir=build "^class .*ContentState(" .)
   ```

3. The holders are constructed once, above the branch — both `val state =` / `val actions =` before
   the `when`, at the same nesting depth. The `-B1` is what makes those bindings visible: a formatter
   breaks a long constructor call onto its own line, so the `val` sits one line *above* every hit and
   a pattern matching only the call prints exactly the half you were not checking.

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B1 \
     "ContentState($\|ContentActions($\|when (.*[Ss]tyle)" .
   ```

4. No look *calls* another look. Every mutual reference must be a comment or a doc link — a bare
   name on a code line means the split has already leaked:

   ```bash
   D=$(dirname "$(grep -rl --include='*.kt' --exclude-dir=build '^class .*ContentState(' .)")
   E=$(grep -hoE '^fun [A-Za-z0-9]+' "$D"/*.kt | awk '{print $2}' | paste -sd'|')
   grep -rnE "($E)" --include='*.kt' "$D" | grep -v ':fun '
   ```

5. The genuinely shared leaves — the ones that may live beside the holders — should be a short,
   `internal`, look-agnostic list:

   ```bash
   grep -n "^internal val \|^internal fun " \
     $(grep -rl --include='*.kt' --exclude-dir=build "^class .*ContentState(" .)
   ```

6. By hand: scroll a look halfway down, swipe the pager two pages along, then switch styles in
   settings and come back. Scroll offset and page must be where you left them — that is the test that
   the holders were built above the branch.
