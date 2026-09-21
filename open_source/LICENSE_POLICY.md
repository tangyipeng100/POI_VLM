# License policy (release staging)

This is a decision record, not a grant of rights. Replace the placeholders
with the authors' chosen licenses before pushing to a public forge.

| Material | Recommended starting point | Extra review |
|---|---|---|
| Original Python/JavaScript/CSS | MIT | Confirm all imported code and icons are compatible. |
| Manuscript and original figures | CC BY 4.0 | Check the conference or journal policy first. |
| Annotation schema and sanitizer | MIT | Keep third-party model names as attribution only. |
| Recorded images and GPS-derived maps | Separate data license or no redistribution | Consent, privacy, map-provider terms, and location sensitivity. |
| VLM raw responses | Usually do not redistribute by default | Provider terms, response IDs, prompts, and personal data. |

The current `examples/assets/sample_front_frame.jpg` is a redacted method
illustration. It must still be cleared by the authors before a public push;
the MIT code license does not grant rights to the photograph. Until that review
is complete, the release page labels the image as a demo asset and does not
imply that the underlying recordings are public.
