import torch
import torch.nn as nn
import torch.nn.functional as F
import copy


class CombinationBlock(nn.Module):
    """For now just linear combination of the two blocks."""

    def __init__(self, block, frozen_block) -> None:
        super().__init__()
        self.block = block
        self.frozen_block = frozen_block
        self.alpha = nn.Parameter(torch.Tensor([0]))

    def forward(self, x):
        print("forward called")
        return F.sigmoid(self.alpha) * self.block(x) + (1 - F.sigmoid(self.alpha)) * self.frozen_block(x)


class SurgicalFineTuningBert(nn.Module):
    def __init__(
        self,
        bert_model,
    ) -> None:
        super().__init__()
        self.bert_model = bert_model
        # copy the model
        self.frozen_bert_model = copy.deepcopy(bert_model)
        # freeze the model
        for param in self.frozen_bert_model.parameters():
            param.requires_grad = False

        self.embedding_block = bert_model.bert.embeddings
        self.combination_blocks = nn.Sequential(
            *[
                CombinationBlock(
                    self.bert_model.bert.encoder.layer[i],
                    self.frozen_bert_model.bert.encoder.layer[i],
                )
                for i in range(len(self.bert_model.bert.encoder.layer))
            ]
        )

    def forward(self, **x):
        print("calling block forward")
        x_input = self.embedding_block(x.input_ids)
        # mask = x.attention_mask
        return self.combination_blocks(x_input)

    def get_alphas(self):
        return [block.alpha for block in self.combination_blocks]

