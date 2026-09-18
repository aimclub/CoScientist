"""Reproduce TransPolymer embeddings with a standalone reimplementation of its
tokenizer (transformers 5.x breaks the original class: the base __init__ calls
get_vocab before the subclass sets self.encoder).

The standalone tokenizer below uses the SAME chemical-aware regex, byte-level
BPE, vocab.json/merges.txt (roberta-base), and special tokens as the original
PolymerSmilesTokenization.py - logic copied verbatim from the repo file.
"""

import json
from functools import lru_cache
import numpy as np
import pandas as pd
import regex as re
import torch
from huggingface_hub import hf_hub_download

status = {"steps": []}


def log(step, ok, detail=""):
    status["steps"].append({"step": step, "ok": bool(ok), "detail": str(detail)})
    print(("OK  " if ok else "FAIL"), step, detail, flush=True)


@lru_cache()
def bytes_to_unicode():
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("\u00a1"), ord("\u00ac") + 1))
        + list(range(ord("\u00ae"), ord("\u00ff") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(2**8):
        if b not in bs:
            bs.append(b)
            cs.append(2**8 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


def get_pairs(word):
    pairs = set()
    prev = word[0]
    for ch in word[1:]:
        pairs.add((prev, ch))
        prev = ch
    return pairs


class StandalonePolymerTokenizer:
    """Verbatim BPE/regex logic from TransPolymer/PolymerSmilesTokenization.py."""

    SMI_REGEX = (
        r"(\-?[0-9]+\.?[0-9]*|\[|\]|SELF|Li|Be|Na|Mg|Al|K|Ca|Co|Zn|Ga|Ge|As|"
        r"Se|Sn|Te|N|O|P|H|I|b|c|n|o|s|p|Br?|Cl?|Fe?|Ni?|Si?|\||\(|\)|\^|=|#|-|"
        r"\+|\\|\/|@|\*|\.|\%|\$)"
    )

    def __init__(self, vocab_file, merges_file, max_len=175):
        with open(vocab_file, encoding="utf-8") as f:
            self.encoder = json.load(f)
        self.decoder = {v: k for k, v in self.encoder.items()}
        self.byte_encoder = bytes_to_unicode()
        with open(merges_file, encoding="utf-8") as f:
            merges = f.read().split("\n")[1:-1]
        self.bpe_ranks = dict(
            zip([tuple(m.split()) for m in merges], range(len(merges)))
        )
        self.cache = {}
        self.pat = re.compile(self.SMI_REGEX)
        self.max_len = max_len
        self.bos = self.encoder["<s>"]
        self.eos = self.encoder["</s>"]
        self.pad = self.encoder["<pad>"]
        self.unk = self.encoder["<unk>"]

    def bpe(self, token):
        if token in self.cache:
            return self.cache[token]
        word = tuple(token)
        pairs = get_pairs(word)
        if not pairs:
            return token
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new_word = []
            i = 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                except ValueError:
                    new_word.extend(word[i:])
                    break
                new_word.extend(word[i:j])
                i = j
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new_word.append(first + second)
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = tuple(new_word)
            if len(word) == 1:
                break
            pairs = get_pairs(word)
        out = " ".join(word)
        self.cache[token] = out
        return out

    def encode(self, text):
        toks = []
        for t in re.findall(self.pat, text):
            t = "".join(self.byte_encoder[b] for b in t.encode("utf-8"))
            toks.extend(self.bpe(t).split(" "))
        ids = [self.encoder.get(t, self.unk) for t in toks]
        ids = [self.bos] + ids + [self.eos]
        mask = [1] * len(ids)
        if len(ids) > self.max_len:
            ids, mask = ids[: self.max_len], mask[: self.max_len]
        pad_n = self.max_len - len(ids)
        return ids + [self.pad] * pad_n, mask + [0] * pad_n


def main():
    vocab_file = hf_hub_download("roberta-base", "vocab.json")
    merges_file = hf_hub_download("roberta-base", "merges.txt")
    tok = StandalonePolymerTokenizer(vocab_file, merges_file, max_len=175)
    ids, mask = tok.encode("[*]CC(C)=CC[*]")
    log("standalone tokenizer", True, f"{len(ids)} ids, head={ids[:10]}")

    ckpt_dir = "third_party/TransPolymer/ckpt/pretrain.pt"
    with open(f"{ckpt_dir}/config.json") as f:
        arch = json.load(f)
    sd = torch.load(
        f"{ckpt_dir}/pytorch_model.bin", map_location="cpu", weights_only=False
    )
    log(
        "load checkpoint",
        True,
        f"hidden={arch.get('hidden_size')} layers={arch.get('num_hidden_layers')} "
        f"{len(sd)} tensors; sample keys: {list(sd)[:3]}",
    )

    from transformers import RobertaConfig, RobertaForMaskedLM

    cfg = RobertaConfig(
        vocab_size=arch.get("vocab_size", 50265),
        hidden_size=arch.get("hidden_size", 768),
        num_hidden_layers=arch.get("num_hidden_layers", 6),
        num_attention_heads=arch.get("num_attention_heads", 12),
        intermediate_size=arch.get("intermediate_size", 3072),
        max_position_embeddings=arch.get("max_position_embeddings", 514),
        type_vocab_size=arch.get("type_vocab_size", 1),
        hidden_dropout_prob=arch.get("hidden_dropout_prob", 0.1),
        attention_probs_dropout_prob=arch.get("attention_probs_dropout_prob", 0.1),
    )
    model = RobertaForMaskedLM(cfg)
    if any(k.startswith("roberta.") for k in sd):
        sd = {
            k[len("roberta.") :]: v for k, v in sd.items() if k.startswith("roberta.")
        }
    missing, unexpected = model.roberta.load_state_dict(sd, strict=False)
    missing = [m for m in missing if "position_ids" not in m]
    log(
        "load weights into RobertaModel",
        len(missing) == 0,
        f"missing={missing[:5]} unexpected={len(unexpected)}",
    )
    model.eval()

    with open("artifacts/psmiles_report.json") as f:
        comps = json.load(f)["valid"]
    names = list(comps)
    fps = []
    with torch.no_grad():
        for n in names:
            ids, mask = tok.encode(comps[n])
            t = torch.tensor([ids])
            m = torch.tensor([mask])
            h = model.roberta(input_ids=t, attention_mask=m).last_hidden_state
            fp = (h * m.unsqueeze(-1)).sum(1) / m.sum(1, keepdim=True).clamp(min=1)
            fps.append(fp.squeeze(0).numpy())
    fps = np.asarray(fps, dtype=np.float32)
    np.save("artifacts/transpolymer_component_fps.npy", fps)
    log("embed components", True, str(fps.shape))

    feat = pd.read_parquet("artifacts/features_plain.parquet")
    ELASTOMER_BLEND = {
        "NR_phr": {"NR": 1.0},
        "ENR_phr": {"NR": 0.75, "ENR": 0.25},
        "BR_phr": {"BD14": 1.0},
        "NBR_phr": {"BD14": 0.70, "PAN": 0.30},
        "EPDM_phr": {"PE": 0.55, "PP": 0.45},
        "IIR_phr": {"PIB": 1.0},
        "FKM_phr": {"PVDF": 0.70, "HFP": 0.30},
        "CR_phr": {"CR": 1.0},
    }
    FPS = dict(zip(names, fps))
    mix = np.zeros((len(feat), fps.shape[1]), dtype=np.float32)
    comp_cols = list(ELASTOMER_BLEND) + ["SBR_phr"]
    for i, row in feat.iterrows():
        phr = {c: row[c] for c in comp_cols}
        total = sum(phr.values())
        if total <= 0:
            continue
        acc = np.zeros(fps.shape[1], dtype=np.float64)
        for c, p in phr.items():
            if p <= 0:
                continue
            share = p / total
            if c == "SBR_phr":
                s = row.get("SBR_styrene_content_pct")
                s = 23.5 if not np.isfinite(s) else min(max(s, 0.0), 60.0) / 100.0
                v = row.get("SBR_vinyl_content_pct")
                v = 0.0 if not np.isfinite(v) else min(max(v, 0.0), 80.0) / 100.0
                blend = {"BD14": (1 - s) * (1 - v), "BD12": (1 - s) * v, "PS": s}
            else:
                blend = ELASTOMER_BLEND[c]
            for comp, w in blend.items():
                acc += share * w * FPS[comp]
        mix[i] = acc.astype(np.float32)
    np.save("artifacts/transpolymer_mix_fps.npy", mix)
    log("mixture fingerprints", True, str(mix.shape))
    status["success"] = True
    with open("artifacts/transpolymer_status.json", "w") as f:
        json.dump(status, f, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        log("fatal", False, traceback.format_exc()[-600:])
        status["success"] = False
        with open("artifacts/transpolymer_status.json", "w") as f:
            json.dump(status, f, indent=2)
