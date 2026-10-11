# Concept
## Important
Check out `images/high-level-concept-poc.png` to see the visual flow.

## Flow
Every flow starts with the image. The image will then go through a transformation pipeline. Each version of the image runs through a text recognition based on standard OCR and for non trivial images where instructions may be hidden in pixel pertubations or other more advanced techniques it requires a specified machine learning model to find those. The model will output if it found something and what it found. Means after either the OCR or the ML runs we have only text. This text we can run through the standard textual based detectors. As we also have capabale classifier models nowadays it also make sense to let each text run through this AI classifier to detect prompt injections which might be a bit more advanced or just not covered by the static detections. Besides the standard textual based detectors we also want to check the relation between the image and the text it contains. A big mismatch between text and image could mean there is something worth investigating. To be able to investigate accordingly and cheap we need a classifier which transform the image into text. Now we have a text which describes the image and the actual text in the image. Both can be send to the AI classifier which can detect if it's an actual prompt injection.

## Current Limitations
- At the moment we are only covering the image content and text-to-image relation. What still remains open is the environment-to-image-content relation. This will not be covered by the current flow, as it would need a dedicated AI agent which is able to understand the environment the image is living in in order to make assumptions about whether the image content is malicious and doesn't fit to the context or fits to the context.

- We don't support image metadata injections at this stage.

- Maybe also add something related to response, not only detection. Like cleaning the image or the pixels (https://arxiv.org/abs/2405.10529)

- No web scanning feature. A use case would be for example a marketplace which hosts images from customers. Also if an attacker can controll a website pixel pertubation is poossible directly through the website (https://arxiv.org/html/2505.11717v4)

- We should also add a way to identify splitted Prompt Injections (like FigStep). This should work based on references. Let's say one image refers another image then the scanner should put them together. Or in general it should combine the text of all images maybe to find splitted words?


## Definitions

- Invisible Text means: Visual weak text, hidden usedata like metadata, alpha-channels, lsb-steganography, embedded containers,... and averserial pertubations
