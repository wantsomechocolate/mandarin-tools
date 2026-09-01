
## Setup translation
from transformers import MarianMTModel, MarianTokenizer
model_name = "Helsinki-NLP/opus-mt-zh-en"
tokenizer = MarianTokenizer.from_pretrained(model_name)
model = MarianMTModel.from_pretrained(model_name)

## Setup pypinyin
from pypinyin import pinyin, lazy_pinyin, Style
from pypinyin.seg.simpleseg import seg


## Input
#text = "我们正在学习如何使用模块进行分词"
text = "滚烫的热水"


## Translate
inputs = tokenizer(text, return_tensors="pt", padding=True)
translated = model.generate(**inputs)
tr = tokenizer.decode(translated, skip_special_tokens=True)[0]


## Get Pronunciation
words = seg(text)
grouped_result = ["".join(lazy_pinyin(word, style=Style.TONE)) for word in words]
pr = ' '.join(grouped_result)


## Output
print(f'{pr} - {tr}')
