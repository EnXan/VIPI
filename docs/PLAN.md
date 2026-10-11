# Plan

1. The transformation pipeline and OCR
    Implement the fixed [image-to-text pipeline](transformation-pipeline/PLAN.md).
    Every image follows the same scaling, rotation, tiling and filter steps.
    The user selects the OCR model; Anamorpher needs no separate runtime path.
    After each adjustment, run OCR and save the text immediately. Assemble
    primary readings by location only after all adjustment steps have finished;
    retain competing readings separately.
    Process views with 1–8 parallel workers (default 4), selectable in CLI and web;
    each worker keeps the adjustment → OCR → save order.

2. The CLI and web interface
    Accept an image and return recognized text through the CLI or a simple local
    web page with image upload/paste and model selection. Show each transformation
    live, followed by animated OCR boxes and the extracted text. Finish with all
    variants, their texts and the combined result. Follow the monochrome VIPI
    brand in assets/. Add dataset selection by category and reference coverage
    reports for selected images. Extra OCR text is allowed; missing reference text
    is invalid. Show paired transformation effects and incomplete/failed images.
    No model ranking, parameter tuning or multilingual preparation. Use the
    [dataset evaluation context](transformation-pipeline/TEST_DATASET.md) for scope.
    Write usage documentation after the implementation works.

3. The prompt detection
    As we should have all the textual information from the image now, we are capable of running detection methods over it. There are several methods we can use. The most straightforward is running known open source scanners over it. This will cover the most obvious injections. For more advanced injections it is required to use an AI classifier model like Jev AI which can give us a probability if it's a prompt injection or not. For invisible instructions it also makes sense to let the AI classifier run over it, as the ML model can only give limited details and it's the task of the classifier to evaluate if this is a real detection. It is still not 100% clear how we want to approach this problem, as invisible instructions are pretty hard to be put in words by an medium advanced ML model. Another important detection method is the relation between the image itself and the text it contains. If they are contrary, it is more likely that the text might be a prompt injection as if they match. This is done through a substep:
    3a. The image-text-relation
    To understand the image-text relation, it makes sense to reuse an existing classifier model which supports image input and classify the image simply. Then we have the image classification as text and the image content as text. With this we have the prerequisites to run them through our AI classifier, which can give us an indication if it's a prompt injection or not.

4. Generate result
    The last step is to put a result from those signals. It is still not clear how we want to define thresholds etc. when something counts as malicious and when not. Also it is still not clear how the signal architecture will look exactly.
