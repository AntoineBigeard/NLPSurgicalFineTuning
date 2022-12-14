import torch
import torch.nn as nn
import torch.nn.functional as F
import copy
import numpy as np
from itertools import chain


class SurgicalFineTuningBert(nn.Module):
    def __init__(
        self,
        bert_model,
    ) -> None:
        super().__init__()
        self.get_extended_attention_mask = bert_model.get_extended_attention_mask
        # copy the model

        self.opti_embedding_block = bert_model.bert.embeddings
        self.frozen_embedding_block = copy.deepcopy(self.opti_embedding_block)
        self.opti_bert_layers = bert_model.bert.encoder.layer
        self.frozen_bert_layers = copy.deepcopy(self.opti_bert_layers)
        self.opti_bert_pooler = bert_model.bert.pooler
        self.frozen_bert_pooler = copy.deepcopy(self.opti_bert_pooler)
        self.opti_bert_classifier = bert_model.classifier
        self.frozen_bert_classifier = copy.deepcopy(self.opti_bert_classifier)

        frozen_params = chain(
            self.frozen_embedding_block.parameters(),
            self.frozen_bert_layers.parameters(),
            self.frozen_bert_pooler.parameters(),
            self.frozen_bert_classifier.parameters(),
        )

        for param in frozen_params:
            param.requires_grad = False

        self.dropout = nn.Sequential(bert_model.dropout)
        if (
            "bert-small" in bert_model.name_or_path
            or "bert-med" in bert_model.name_or_path
        ):
            self.alphas = nn.Parameter(
                torch.zeros(len(bert_model.bert.encoder.layer) + 3)
            )
        else:
            self.alphas = nn.Parameter(
                torch.zeros(len(bert_model.bert.encoder.layer) + 1)
            )

    def forward(self, x):
        input_ids, attention_mask = x["input_ids"], x["attention_mask"]
        extended_attention_mask = self.get_extended_attention_mask(
            attention_mask, input_ids.size()
        )

        alpha_embeddings, alphas_layers, alpha_pooler, alpha_classifier = (
            self.alphas[0],
            self.alphas[:-2],
            self.alphas[-2],
            self.alphas[-1],
        )

        x_opti, x_frozen = self.opti_embedding_block(
            input_ids
        ), self.frozen_embedding_block(input_ids)

        a = alpha_embeddings.sigmoid()
        x = a * self.opti_embedding_block(input_ids) + (
            1 - a
        ) * self.frozen_embedding_block(input_ids)

        for i in range(len(self.opti_bert_layers)):
            a = alphas_layers[i].sigmoid()
            if i > 0:
                x_opti, x_frozen = x, x
            x = (
                a
                * self.opti_bert_layers[i](
                    x_opti, attention_mask=extended_attention_mask
                )[0]
                + (1 - a)
                * self.frozen_bert_layers[i](
                    x_frozen, attention_mask=extended_attention_mask
                )[0]
            )

        a = alpha_pooler.sigmoid()
        x = a * self.opti_bert_pooler(x) + (1 - a) * self.frozen_bert_pooler(x)
        x = self.dropout(x)

        a = alpha_classifier.sigmoid()
        x = a * self.opti_bert_classifier(x) + (1 - a) * self.frozen_bert_classifier(x)

        return x

    def forward_alphas(self, x, alphas):
        alpha_embeddings, alphas_layers, alpha_pooler, alpha_classifier = (
            alphas[0],
            alphas[:-2],
            alphas[-2],
            alphas[-1],
        )

        input_ids, attention_mask = x["input_ids"], x["attention_mask"]
        extended_attention_mask = self.get_extended_attention_mask(
            attention_mask, input_ids.size()
        )

        a = alpha_embeddings.sigmoid()
        x = a * self.opti_embedding_block(input_ids) + (
            1 - a
        ) * self.frozen_embedding_block(input_ids)

        x_opti, x_frozen = self.opti_embedding_block(
            input_ids
        ), self.frozen_embedding_block(input_ids)

        for i in range(len(self.opti_bert_layers)):
            a = alphas_layers[i].sigmoid()
            if i > 0:
                x_opti, x_frozen = x, x
            x = (
                a
                * self.opti_bert_layers[i](
                    x_opti, attention_mask=extended_attention_mask
                )[0]
                + (1 - a)
                * self.frozen_bert_layers[i](
                    x_frozen, attention_mask=extended_attention_mask
                )[0]
            )

        a = alpha_pooler.sigmoid()
        x = a * self.opti_bert_pooler(x) + (1 - a) * self.frozen_bert_pooler(x)
        x = self.dropout(x)

        a = alpha_classifier.sigmoid()
        x = a * self.opti_bert_classifier(x) + (1 - a) * self.frozen_bert_classifier(x)

        return x

    def get_alphas(self):
        return [float(a.sigmoid()) for a in self.alphas]
