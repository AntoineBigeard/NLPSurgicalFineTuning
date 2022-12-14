import yaml
import datasets
import logging
import transformers
import numpy as np
import pandas as pd
from typing import List
from collections import defaultdict


logging.basicConfig()
LOG = logging.getLogger(__name__)

datasets.logging.set_verbosity_error()


def read_yaml_config_file(path_config: str):
    with open(path_config) as conf:
        return yaml.load(conf, yaml.FullLoader)


def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def model2hfname(model: str) -> str:
    return {
        "bert-tiny": "prajjwal1/bert-tiny",
        "bert-mini": "prajjwal1/bert-mini",
        "bert-small": "prajjwal1/bert-small",
        "bert-med": "prajjwal1/bert-medium",
        "bert-large": "prajjwal1/bert-large",
    }[model]


def dataset2hfname(dataset: str) -> str:
    return {
        "mnli": ("multi_nli",),
        "amazon_video": ("amazon_us_reviews", "Video_v1_00"),
        "amazon_books": ("amazon_us_reviews", "Books_v1_00"),
        "amazon_electronics": ("amazon_us_reviews", "Mobile_Electronics_v1_00"),
        "amazon_kitchen": ("amazon_us_reviews", "Kitchen_v1_00"),
        "amazon_shoes": ("amazon_us_reviews", "Shoes_v1_00"),
        "amazon_grocery": ("amazon_us_reviews", "Grocery_v1_00"),
        "amazon_luggage": ("amazon_us_reviews", "Luggage_v1_00"),
        "tweet_eval": ("tweet_eval", "offensive"),
        "civil_comments": ("civil_comments",),
    }[dataset]


def stop_tokens(tokenizer, stop_string: str = ".") -> int:
    tokens = []
    for idx in range(len(tokenizer)):
        if tokenizer.decode(idx) == stop_string:
            tokens.append(idx)
    return tokens


def get_data(dataset: str, num_samples: int):
    if "amazon" in dataset:
        d = datasets.load_dataset(
            dataset2hfname(dataset)[0], dataset2hfname(dataset)[1]
        )["train"]
        filter_fn = lambda rows: ["sex" not in r.lower() for r in rows["review_body"]]
        d = d.filter(filter_fn, batched=True, batch_size=None)
        df = (
            pd.DataFrame(
                {"star_rating": d["star_rating"], "review_body": d["review_body"]}
            )
            .sample(frac=1)
            .reset_index(drop=True)
        )
        df["star_rating"] -= 1
        num_samples_in_df = df.groupby(["star_rating"])["review_body"].count().min()
        num_samples_final = min(num_samples_in_df, num_samples)
        df = (
            pd.concat(
                [df[df["star_rating"] == i].iloc[:num_samples_final] for i in range(5)]
            )
            .sample(frac=1)
            .reset_index(drop=True)
        )

        return {"x": list(df["review_body"]), "y": list(df["star_rating"])}

    elif dataset == "tweet_eval":
        d = datasets.load_dataset(
            dataset2hfname(dataset)[0], dataset2hfname(dataset)[1]
        )["train"]
        filter1 = lambda rows: [r is not None and len(r) > 0 for r in rows["text"]]
        filter2 = lambda rows: [r is not None and r in [0, 1] for r in rows["label"]]
        # filter_fn = lambda rows: [clean(r, no_emoji=True) for r in rows["text"]]
        d = d.filter(filter1, batched=True, batch_size=None)
        d = d.filter(filter2, batched=True, batch_size=None)
        x = [r for r in d["text"]]
        y = [int(r) for r in d["label"]]

        df = defaultdict(lambda: [None] * 2 * num_samples)
        counts = defaultdict(int)
        end_idx = 0
        for idx in range(len(y)):
            c = counts[y[idx]]
            if c < num_samples:
                df["x"][c * 2 + y[idx]] = x[idx]
                df["y"][c * 2 + y[idx]] = y[idx]
                # print(df["x"][c * 2 + y[idx]], df["y"][c * 2 + y[idx]])
                counts[y[idx]] += 1
                end_idx += 1

        return df, end_idx
    elif dataset == "civil_comments":
        d = datasets.load_dataset(dataset2hfname(dataset)[0])["train"]
        filter1 = lambda rows: [r is not None and len(r) > 0 for r in rows["text"]]
        filter2 = lambda rows: [r is not None and r >= 0.0 for r in rows["toxicity"]]
        d = d.filter(filter1, batched=True, batch_size=None)
        d = d.filter(filter2, batched=True, batch_size=None)
        x = [r for r in d["text"]]
        y = [int(0) if r <= 0.5 else int(1) for r in d["toxicity"]]

        df = defaultdict(lambda: [None] * 2 * num_samples)
        counts = defaultdict(int)
        end_idx = 0
        for idx in range(len(y)):
            c = counts[y[idx]]
            if c < num_samples:
                df["x"][c * 2 + y[idx]] = x[idx]
                df["y"][c * 2 + y[idx]] = y[idx]
                counts[y[idx]] += 1
                end_idx += 1

        return df, end_idx

    else:  ## To be filled with the logic to extract other datasets
        raise NotImplementedError()


def get_single_dataset(
    ds: str,
    train_pct: List[int],
    val_pct: List[int],
    n_classes: int,
    n_train: int,
    n_val: int = 100,
):

    train_data = defaultdict()
    val_data = defaultdict()

    train_samples = int((n_train * train_pct) / 100)
    val_samples = int((n_val * val_pct) / 100)
    df = get_data(
        ds,
        train_samples + val_samples,
    )
    if (
        len(df["x"]) == train_samples + val_samples
    ):  # If we had enough datapoints to get the number of samples we want
        train_data["x"] = df["x"][: n_classes * train_samples]
        train_data["y"] = df["y"][: n_classes * train_samples]
        val_data["x"] = df["x"][n_classes * train_samples :]
        val_data["y"] = df["y"][n_classes * train_samples :]
    else:  # Otherwise, we use % of train samples wanted to make our cut
        share_train, df_length = train_samples / (train_samples + val_samples), len(
            df["x"]
        )
        stop_point = int(share_train * df_length)

        train_data["x"] = df["x"][:stop_point]
        train_data["y"] = df["y"][:stop_point]
        val_data["x"] = df["x"][stop_point:]
        val_data["y"] = df["y"][stop_point:]

    return train_data, val_data


def get_train_val_pcts(
    train_datasets: List[str],
    val_datasets: List[str],
    train_percentages: List[int],
    val_percentages: List[int],
):
    pcts = {}
    for i, ds in enumerate(train_datasets):
        pcts[ds] = {"train": train_percentages[i], "val": 0}
    for i, ds in enumerate(val_datasets):
        if ds in pcts:
            pcts[ds]["val"] = val_percentages[i]
        else:
            pcts[ds] = {"train": 0, "val": val_percentages[i]}
    return pcts


def get_train_val_datasets(
    train_datasets: List[str],
    val_datasets: List[str],
    train_percentages: List[int],
    val_percentages: List[int],
    n_train: int,
    n_val: int,
):
    train_val_pcts = get_train_val_pcts(
        train_datasets, val_datasets, train_percentages, val_percentages
    )
    train_data = {"x": [], "y": []}
    val_data = {"x": [], "y": []}
    for ds in set(train_datasets + val_datasets):
        n_classes = 5 if "amazon" in ds else 2
        temp_train, temp_val = get_single_dataset(
            ds,
            train_val_pcts[ds]["train"],
            train_val_pcts[ds]["val"],
            n_classes,
            n_train,
            n_val,
        )
        train_data["x"].extend(temp_train["x"])
        train_data["y"].extend(temp_train["y"])
        val_data["x"].extend(temp_val["x"])
        val_data["y"].extend(temp_val["y"])

    return train_data, val_data


def get_model_and_tokenizer(model: str, Cls, **model_kwargs):
    hf_model_name = model2hfname(model)

    m = Cls.from_pretrained(hf_model_name, **model_kwargs)
    if isinstance(m, transformers.GPT2LMHeadModel):
        m.transformer.gradient_checkpointing_enable()

    tok = transformers.AutoTokenizer.from_pretrained(hf_model_name)

    if tok.pad_token_id is None:
        if Cls == transformers.AutoModelForCausalLM:
            tok.pad_token = tok.eos_token
        else:
            print("Adding pad token to tokenizer")
            tok.add_special_tokens({"pad_token": "[PAD]"})
            tok.pad_token = "[PAD]"
    return m, tok


def metric_for_dataset(dataset: str):
    return {
        "mnli": "classification accuracy",
        "amazon_books": "classification accuracy",
        "amazon_video": "classification accuracy",
        "tweet_eval": "classification accuracy",
        "civil_comments": "classification accuracy",
    }[dataset]


def early_stop_thresold(dataset: str):
    return {
        "mnli": 0.95,
        "amazon_books": 0.95,
        "amazon_video": 0.95,
        "tweet_eval": 0.95,
        "civil_comments": 0.95,
    }[dataset]
