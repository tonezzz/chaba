"""SentencePiece base tokenizer for Thai (no inter-word spaces -> SP unigram/BPE
operating on raw text is the standard choice).

Train:
  python -m ncmthai.sp_tokenizer --input data/thai_corpus.txt \
      --vocab 8192 --out data/spm_thai

Produces spm_thai.model + spm_thai.vocab. The SPTokenizer class below wraps it
with the upstream Tokenizer interface (encode/decode/{eos,pad}_token_id) and is
registered as pre_tokenizer name "spm" for VQVAETokenizer.from_config.
"""
import argparse

from tokenization.tokenizer import Tokenizer
from utils.registry import tokenizers


class SPTokenizer(Tokenizer):
    def __init__(self, model_path):
        super().__init__()
        import sentencepiece as spm
        self.sp = spm.SentencePieceProcessor(model_file=model_path)
        self.vocab_size = self.sp.get_piece_size()
        self.eos_token_id = self.sp.eos_id()   # 2 by convention
        self.pad_token_id = self.sp.pad_id()   # 3 (requires --pad_id in training)
        self.bos_token_id = self.sp.bos_id()

    @classmethod
    def from_config(cls, config):
        return cls(config.model_path)

    def encode(self, text: str):
        return list(self.sp.encode(text))

    def decode(self, ids, skip_special_tokens: bool = False):
        ids = [int(i) for i in ids]
        if skip_special_tokens:
            ids = [i for i in ids if i not in
                   (self.eos_token_id, self.pad_token_id, self.bos_token_id)]
        return self.sp.decode(ids)


tokenizers["spm"] = "ncmthai.sp_tokenizer.SPTokenizer"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--vocab", type=int, default=8192)
    ap.add_argument("--out", required=True)
    ap.add_argument("--type", default="bpe", choices=["bpe", "unigram"])
    ap.add_argument("--chars", type=int, default=2_000_000_00,
                    help="cap characters fed to SP trainer")
    a = ap.parse_args()
    import sentencepiece as spm
    spm.SentencePieceTrainer.train(
        input=a.input, model_prefix=a.out, vocab_size=a.vocab,
        model_type=a.type, character_coverage=0.9995,
        bos_id=1, eos_id=2, pad_id=3, unk_id=0,
        input_sentence_size=a.chars // 40, shuffle_input_sentence=True,
        train_extremely_large_corpus=False)
    print(f"wrote {a.out}.model / {a.out}.vocab")


if __name__ == "__main__":
    main()
