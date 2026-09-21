# Paper snapshot

## POI-Guided Vision-Language Decision Making for Outdoor Robot Local Navigation

**Publication status:** the manuscript is accepted/being published. The final
publication URL will be added here when it is available. The current project
version is the authors' release copy and may receive small editorial updates.

### Abstract

We present an interpretable offline decision framework for outdoor robot local
navigation. A drivable-area mask is converted into a compact set of numbered
points of interest (POIs) using polygon boundary geometry. A top-down route
trend is rendered as a second view, and a vision-language model chooses a
structured local action from the front-view POIs and route context. A local web
annotation tool records `go_to_poi`, `rotate`, and `skip` labels, while strict
and relaxed target metrics expose both action-level and candidate-level errors.
On the current 150-frame nighttime evaluation, GPT-5.5 reaches 92.0% action
accuracy and 64.7% strict target accuracy; Qwen-H800 reaches 91.3% and 78.7%,
respectively. These are offline frame-level results, not closed-loop robot
success rates or safety guarantees.

### Method in one line

```text
RGB frame -> drivable mask -> polygon POIs -> front/route question image -> structured VLM action
```

The open implementation includes the polygon POI stage and the surrounding
schema/annotation/evaluation utilities. The segmentation model is treated as a
replaceable front end; the original 5000-image training set is not bundled.

### Reported snapshot

| Split / model | Samples | Action accuracy | Strict target | Relaxed target |
|---|---:|---:|---:|---:|
| Night / GPT-5.5 | 150 | 138/150 (92.0%) | 97/150 (64.7%) | 100/150 (66.7%) |
| Night / Qwen-H800 | 150 | 137/150 (91.3%) | 118/150 (78.7%) | 118/150 (78.7%) |

The evaluation uses human labels and is intentionally framed as evidence that
the decision interface is feasible and inspectable. It does not claim SOTA,
closed-loop navigation, or physical safety.

### Materials

- [Current author manuscript](paper/manuscript.md)
- [Selected paper figures](paper/figures/)
- [Publication link placeholder](PUBLICATION.md)

The manuscript copy is the current author release snapshot. Editable source
figures, raw recordings, exact route data, and internal annotation exports are
intentionally excluded from this public folder and remain subject to separate
privacy, rights, and venue review.
