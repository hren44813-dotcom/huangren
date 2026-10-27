# Failure Retry Rules

Use these rules after each generated image or batch.

## Retry Once Immediately

Retry the failed module once when:

- API returns transient error.
- Image ratio does not match the requested ratio or platform size.
- Product is badly distorted.
- Text is garbled.
- A fake logo, fake certification, rating, review, or unsupported claim appears.
- Model identity changes significantly.

## Shorten Prompt on Retry

Keep:

- Campaign Style Lock
- Model Identity Lock if needed
- Product reference sentence
- Module task
- Headline and labels
- Avoid list

Remove:

- Long descriptive prose
- Too many scene props
- Extra body copy
- Multiple competing visual metaphors

## Safer Regeneration Patterns

- Text failure: use fewer labels; replace paragraphs with icons.
- Product drift: make product larger, front-facing, and explicitly preserve visible structure.
- Model drift: crop below eyes, use side/back view, ghost mannequin, or product-only detail.
- Fake brand prop: specify “generic unbranded props only”.
- Unsupported claim: replace with “visible package claim” or remove the claim.
- Wrong size: regenerate with the exact requested canvas, such as `wide 16:9 horizontal module, same size as the full set` or `vertical 900x1200 Russian Ozon/Wildberries ecommerce detail image`.
