# Chatterbox Turbo Tag Research

This is an inactive reference recovered from the April 14 Claude transcript. It
is not loaded by Handsfree unless copied into `chatterbox_guidance.md` or a user
override at `~/.handsfree/prompts/chatterbox_guidance.md`.

## Source

The detailed result said the authoritative list lives in Chatterbox Turbo's
`added_tokens.json`:

- Local cache: `/Users/stevenedgar/.cache/huggingface/hub/models--ResembleAI--chatterbox-turbo/snapshots/<sha>/added_tokens.json`
- Online equivalent: https://huggingface.co/ResembleAI/chatterbox-turbo/blob/main/added_tokens.json

All 19 tags occupy token IDs 50257 through 50275, immediately after the GPT-2
base vocabulary. They are added tokens, so the model sees one discrete symbol per
tag instead of literal bracketed letters.

## Emotion Tags

These 10 affect overall delivery and work best at the start of a sentence.

| Tag | Token ID |
|---|---:|
| `[angry]` | 50257 |
| `[fear]` | 50258 |
| `[surprised]` | 50259 |
| `[whispering]` | 50260 |
| `[advertisement]` | 50261 |
| `[dramatic]` | 50262 |
| `[narration]` | 50263 |
| `[crying]` | 50264 |
| `[happy]` | 50265 |
| `[sarcastic]` | 50266 |

## Vocal Sound Tags

These 9 are vocal sound effects and can go mid-sentence.

| Tag | Token ID |
|---|---:|
| `[clear throat]` | 50267 |
| `[sigh]` | 50268 |
| `[shush]` | 50269 |
| `[cough]` | 50270 |
| `[groan]` | 50271 |
| `[sniff]` | 50272 |
| `[gasp]` | 50273 |
| `[chuckle]` | 50274 |
| `[laugh]` | 50275 |

Exact strings matter: brackets, lowercase, and spaces as shown. The transcript
called out two specific mistakes:

- Use `[whispering]`, not `[whisper]`.
- Use `[clear throat]`, not `[clear_throat]`, `[clears throat]`, or `[throat clear]`.

## Documented Vs. Tokenizer-Backed

- Resemble's public README/model-card examples promoted `[laugh]`, `[chuckle]`,
  and `[cough]`, with wording like "and more".
- A Resemble staff reply on Hugging Face discussion 21 reportedly listed the 9
  sound-effect tags: `[clear throat]`, `[sigh]`, `[shush]`, `[cough]`, `[groan]`,
  `[sniff]`, `[gasp]`, `[chuckle]`, and `[laugh]`.
- The 10 emotion tags are tokenizer-backed but were not promoted as prominently
  in prose docs.
- The transcript noted that community reports described tags as hit-or-miss, but
  useful when the reference audio is short and clean.

## Turbo Vs. Original Chatterbox

- Original `ResembleAI/chatterbox` and `chatterbox-multilingual` do not support
  these paralinguistic tokens.
- `ResembleAI/chatterbox-turbo` uses a GPT-2 BPE tokenizer with the 19 added
  tokens above.

## Practical Guidance

- Whitelist exactly these 19 strings when validating tags.
- Strip unsupported bracketed tags before TTS so they are not read aloud.
- Put a tag immediately before the sentence or phrase it colors.
- Avoid stacking tags unless testing; reliability varies.
- Tags not in the tokenizer, such as `[deep breath]`, `[exhale]`, `[panting]`,
  and `[yawn]`, should be treated as unsupported.

## Links From The Transcript

- https://huggingface.co/ResembleAI/chatterbox-turbo/blob/main/added_tokens.json
- https://huggingface.co/ResembleAI/chatterbox-turbo
- https://huggingface.co/ResembleAI/chatterbox-turbo/discussions/21
- https://github.com/resemble-ai/chatterbox/issues/492
- https://github.com/resemble-ai/chatterbox
- https://resemble-ai.github.io/chatterbox_turbo_demopage/
- https://www.resemble.ai/chatterbox-turbo/
- https://github.com/wobba/ComfyUI-ChatterBox-Turbo
- https://blog.fal.ai/chatterbox-turbo-is-now-available-on-fal/
