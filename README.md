# CuteLingoExpress
Automagically translate ts-files for Qt-internationalization. Just give it the file and source and target language and off you go.

# Setup
`pip install requirements.txt`
Only use the translators-package 5.3.1 - the newest did not work.

# Usage
## Invocation
Run it with positional arguments for the ts-file (will be edited in-place) and the ISO 639-1 country-codes for the source and target language. For further information about those: https://pypi.org/project/translators/ 
```
python auto_trans.py testing/numerus.ts de cn
python auto_trans.py testing/helloworld.ts en cn
```

## Handling errors
* Chosen backend for the translation is Google. But in roundabout 20% of the runs it is not starting, so CTRl+C and retry.

# Checking results
* Best done via `diff` from your favorite version-control.

## Naming?
* "CuteLingoExpress": Blending "cute" (Qt)," "lingo" and "express," it conveys a tool that rapidly and delightfully translates Qt content, emphasizing both efficiency and charm.
* applied some design-thinking methodologies with GPT
