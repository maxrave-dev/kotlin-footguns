---
name: dont-slice-one-circle-between-unrelated-measures
description: Put several measures that share no whole onto concentric arcs instead of slicing one circle between them, cap the largest sweep short of 360°, and draw value wedges over a full-ring track. Use when a donut/pie is about to encode counts that do not add up to anything, when the biggest ring looks identical to a full one, or when an "almost nothing here" bucket reads as a missing tick.
---

# Concentric arcs, not one sliced circle

Three counts — distinct items, distinct groups, distinct entities — measure three different things
over the same window. They do not sum to a total, so a pie or a donut split between them draws each
one as a fraction of a quantity that does not exist. Concentric rings put them on one common scale
(each swept against the largest of the three) without claiming they are parts of each other.

```kotlin
// adapted: three rows, outermost first, each swept against the largest of them
val max = rows.maxOf { it.value }.coerceAtLeast(1)
Canvas(Modifier.size(diameter)) {
    val stroke = size.minDimension * 0.085f
    rows.forEachIndexed { i, row ->
        val radius = size.minDimension / 2f - stroke / 2f - i * stroke * 1.55f
        if (radius <= 0f) return@forEachIndexed
        val topLeft = Offset(center.x - radius, center.y - radius)
        val arcSize = Size(radius * 2, radius * 2)
        drawArc(track, 0f, 360f, false, topLeft, arcSize, style = Stroke(stroke))
        drawArc(
            color = ringColors[i], startAngle = -90f,
            sweepAngle = 360f * 0.92f * (row.value.toFloat() / max),
            useCenter = false, topLeft = topLeft, size = arcSize,
            style = Stroke(stroke, cap = StrokeCap.Round),
        )
    }
}
```

## Traps

**A circle divided between measures asserts they are parts of one whole.** That assertion is made by
the *shape*, before any label is read, and no caption undoes it — the reader has already computed
"items are 46% of … something". Concentric arcs make the same three numbers comparable (same angular
scale, same start angle) while asserting nothing about their sum. The rule generalises: reach for a
pie only when the parts are a partition of a quantity you can name in one word.

**A full ring and a nearly-full ring are the same picture.** At 360° the arc's start and end meet, so
the endpoint — the only thing that encodes the value — vanishes. Cap the largest sweep short of the
circle (`× 0.92` here, leaving 28.8°) so every ring, including the biggest, has a locatable end.

**A round cap eats the gap you just budgeted, and it eats more on smaller rings.** `StrokeCap.Round`
extends the drawn arc by half a stroke width past each endpoint. Half a stroke is a *length*, so its
cost in *degrees* is `(stroke / 2) / radius` — which grows as the radius shrinks. With
`stroke = 0.085 d` and the 1.55 step above, the three rings overhang 10.6°, 15.0° and 25.1°. So the
28.8° gap is really 18.2° on the outer ring and **3.7° on the inner one**: if the innermost row ever
holds the maximum, the cap is defeated and its ring reads as closed. Either order the rows so the
largest lands on the largest radius, compute the cap per ring from its own radius, or use a butt cap.

**A `radius <= 0` guard silently drops a row.** With that stroke and step the radii run 0.4575 d,
0.3257 d, 0.1940 d, 0.0622 d, then negative — so the guard first fires on a **fifth** row, and the
fourth is already a ring whose stroke is wider than its own radius, left with an inner radius of
0.02 d, which reads as a blob rather than as an arc. Adding a measure to this chart is therefore not free, and the
failure is a row that is simply not on screen. Same silent-drop shape as
`mosaic-arrangements-must-be-hole-free`: if a layout arm can skip an entry, it must say so.

**Draw the value over a full-ring track, not on its own.** Without a dark ring running the whole 360°
behind it, an hour (or a bucket) with one event and an hour with none look nearly identical — the eye
reads a short arc as a *missing tick* rather than as "almost nothing here". The track supplies the
"here is the slot, and it is nearly empty" reading that a short mark alone cannot.

**Draw the value wedge and its track with the same function and the same angles.** In a 24-wedge
clock the value differs from the track only in outer radius; sharing `startDeg`/`sweepDeg` is what
makes the two register exactly, at any canvas size:

```kotlin
drawWedge(center, inner, outer, start, sweep, trackColor)
if (count > 0) drawWedge(center, inner, inner + (outer - inner) * (count.toFloat() / max), start, sweep, valueColor)
```

Recomputing the value's geometry from a second expression is how a one-pixel misregistration gets
in, and it will show as a rim of track peeking out along one edge of every wedge.

**Put the gap in the sweep, not between the shapes.** Each wedge takes `sweep = slice - gap` with
`start` offset by `gap / 2`, so the separators are angular and stay even at every radius. Insetting
the wedges by a fixed number of pixels instead gives wide gaps near the hole and hairlines at the rim.

**Legend colours must differ in hue *and* survive greyscale.** Three rings at matched lightness look
deliberate but collapse into one grey when the screenshot is printed or the reader is colour-blind —
the radius already encodes each row's position and the legend repeats that order, so give the legend
a non-colour cue (outer/middle/inner, or a leader line) and never rely on a coloured dot alone.

The other half of honest chart geometry is honest chart *scope*: when a chart can only classify part
of its input, say so on the chart — `partial-chart-must-say-so`.

## Verifying it

Run these from the repository root. They are read-only.

1. Every arc sweep in the codebase. A literal `360f` on a value arc (rather than on a track) is a
   value that can reach a closed ring:

   ```bash
   grep -rn --include='*.kt' -A4 "drawArc(" . | grep -v '/build/' | grep -E "sweepAngle|360f"
   ```

2. Re-derive the radius series and the round-cap overhang for your own stroke and step. Change the
   `0.085` and `1.55` to match your chart; any ring whose overhang approaches the gap you budgeted
   is a ring that will read as closed:

   ```bash
   LC_ALL=C awk 'BEGIN{s=0.085; for(i=0;i<5;i++){r=0.5-s/2-i*s*1.55;
     if(r>0) printf "ring %d  radius %.4f d  cap-overhang %.1f deg\n",i,r,2*(s/2)/r*57.29578;
     else printf "ring %d  radius %.4f d  DROPPED by the radius<=0 guard\n",i,r}}'
   ```

   Prints `10.6`, `15.0`, `25.1`, `78.2` degrees and then a dropped fifth ring.

3. By hand: feed the chart a data set where the **innermost** row holds the maximum. If its ring
   looks closed, the cap is being eaten by the cap style and needs to be computed per ring.
