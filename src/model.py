#!/usr/bin/env python

import torch
from torch import nn
import torch.nn.functional as F

class Embedding(nn.Module):
    def __init__(self, embd_dim=5, num_pts=200):
        super().__init__()
        self.num_pts = num_pts
        self.embd_dim = embd_dim
        self.embedding = nn.Embedding(num_pts, embd_dim)

    def forward(self, batch_ids):
        pts_embedded = self.embedding(batch_ids)
        return pts_embedded


class Encoder(nn.Module):
    def __init__(self, enc_dim=64, dec_dim=32, input_dim=8,
                 embedding_layer=None, GRU_LSTM='GRU', is_bidirectional=True):
        super().__init__()
        self.enc_dim = enc_dim
        self.dec_dim = dec_dim

        self.GRU_LSTM = GRU_LSTM
        self.is_bidirectional = is_bidirectional

        self.dropout = nn.Dropout(p = 0.5)

        self.embedding_layer = embedding_layer
        if embedding_layer is not None:
            embd_dim = embedding_layer.embd_dim
        else:
            embd_dim = 0

        self.input_dim = input_dim + embd_dim
        if GRU_LSTM == 'GRU':
            self.rnn = nn.GRU(self.input_dim, self.enc_dim,
                              bidirectional=is_bidirectional)
        if GRU_LSTM == 'LSTM':
            self.rnn = nn.LSTM(self.input_dim, self.enc_dim,
                               bidirectional=is_bidirectional)

        if self.is_bidirectional:
            self.fc = nn.Linear(enc_dim*2, dec_dim)
        else:
            self.fc = nn.Linear(enc_dim, dec_dim)

    def forward(self, one_batch):
        '''
        input_batch: enc_len * size * input_dim
        '''
        batch_ids = one_batch[0]

        rnn_input = one_batch[1].permute(1, 0, 2)

        enc_len = rnn_input.size(0)

        if self.embedding_layer is not None:
            pts_embedded = self.embedding_layer(
                batch_ids).unsqueeze(0).repeat(enc_len, 1, 1)
            rnn_input = torch.cat((rnn_input, pts_embedded), dim=2)

        rnn_input = self.dropout(rnn_input) #apply dropout

        if self.GRU_LSTM == 'GRU':
            outputs, hidden = self.rnn(rnn_input)
        elif self.GRU_LSTM == 'LSTM':
            outputs, (hidden, _) = self.rnn(rnn_input)

        if self.is_bidirectional:
            hidden = torch.tanh(
                self.fc(torch.cat((hidden[-2, :, :], hidden[-1, :, :]), dim=-1)))
        else:
            hidden = torch.tanh(self.fc(hidden[-1, :, :]))
        return outputs, hidden


class Decoder(nn.Module):
    def __init__(self, enc_dim=64, dec_dim=32, dec_input_dim=4, enc_len=48,
                 embedding_layer=None, attention_ind=False, GRU_LSTM='GRU', is_bidirectional=True):
        super().__init__()
        self.enc_dim = enc_dim
        self.dec_dim = dec_dim
        self.attention_ind = attention_ind

        self.GRU_LSTM = GRU_LSTM
        self.is_bidirectional = is_bidirectional

        self.embedding_layer = embedding_layer
        if embedding_layer is not None:
            embd_dim = embedding_layer.embd_dim
        else:
            embd_dim = 0
        self.dec_input_dim = dec_input_dim + embd_dim
        if GRU_LSTM == 'GRU':
            self.rnn = nn.GRU(self.dec_input_dim, dec_dim)
        elif GRU_LSTM == 'LSTM':
            self.rnn = nn.LSTM(self.dec_input_dim, dec_dim)
        self.fc = nn.Linear(dec_dim, 1)

        self.dropout = nn.Dropout(p=0.5)  # Monte Carlo Dropout

        if self.attention_ind:
            self.attn = nn.Linear(self.dec_input_dim + dec_dim, enc_len)
            if self.is_bidirectional:
                self.attn_combined = nn.Linear(
                    self.dec_input_dim + 2*enc_dim, self.dec_input_dim)
            else:
                self.attn_combined = nn.Linear(
                    self.dec_input_dim + enc_dim, self.dec_input_dim)

    def forward(self, one_batch, encoder_outputs, hidden):
        '''
        input: size * input_dim
        batch_ids: size
        '''
        # change size to 1 * size * dim
        batch_ids = one_batch[0]
        y_ = one_batch[2].permute(1, 0, 2)
        encoder_outputs = encoder_outputs.permute(1, 0, 2)

        rnn_input = y_[[0], :, :]
        rnn_input[rnn_input != rnn_input] = 0

        cell_state = torch.zeros_like(hidden).unsqueeze(0)

        output_list = []
        for i in range(1, 13):
            if self.embedding_layer is not None:
                pts_embedded = self.embedding_layer(batch_ids).unsqueeze(0)
                rnn_input = torch.cat((rnn_input, pts_embedded), dim=2)

            rnn_input = self.dropout(rnn_input)  # Apply dropout

            if self.attention_ind:
                attn_weights = F.softmax(
                    self.attn(torch.cat((rnn_input[0, :, :], hidden), dim=1)))

                attn_applied = torch.bmm(
                    attn_weights.unsqueeze(1), encoder_outputs)
                attn_applied = attn_applied.squeeze(1)

                rnn_input = rnn_input.squeeze(0)
                rnn_input = self.attn_combined(
                    torch.cat((attn_applied, rnn_input), dim=1))
                rnn_input = rnn_input.unsqueeze(0)

            hidden = hidden.unsqueeze(0)
            if self.GRU_LSTM == 'GRU':
                output, hidden = self.rnn(rnn_input, hidden)
            elif self.GRU_LSTM == 'LSTM':
                output, (hidden, cell_state) = self.rnn(
                    rnn_input, (hidden, cell_state))
            assert (output == hidden).all()
            # 1 * size * dec_dim

            output = output.squeeze(0)
            hidden = hidden.squeeze(0)
            output = self.fc(output)        # output with size*1 prediction

            rnn_input = y_[i, :, 1:]
            rnn_input = torch.cat((rnn_input, output), dim=1)
            rnn_input = rnn_input.unsqueeze(0)

            output_list.append(output)

        y_pred = torch.cat(output_list, dim=1).transpose(0, 1)

        return y_pred


class Seq2Seq(nn.Module):
    def __init__(self, enc_dim=64, dec_dim=32, input_dim=4, K=5, enc_len=48,
                 embedding_dim=5, attention_ind=False, GRU_LSTM='GRU',
                 is_bidirectional=False, n_turbines=200,
                 device=torch.device('cpu')):

        super().__init__()

        self.enc_dim = enc_dim
        self.dec_dim = dec_dim
        self.enc_input_dim = input_dim + K - 1
        self.dec_input_dim = input_dim
        self.device = device

        if embedding_dim > 0:
            self.embedding_layer = Embedding(embedding_dim, num_pts=n_turbines)
        else:
            self.embedding_layer = None

        self.attention_ind = attention_ind

        if GRU_LSTM == 'GRU':
            self.encoder = Encoder(enc_dim, dec_dim, self.enc_input_dim, self.embedding_layer,
                                   GRU_LSTM='GRU', is_bidirectional=is_bidirectional)
            self.decoder = Decoder(enc_dim, dec_dim, self.dec_input_dim, enc_len,
                                   self.embedding_layer, self.attention_ind, GRU_LSTM='GRU',
                                   is_bidirectional=is_bidirectional)
        if GRU_LSTM == 'LSTM':
            self.encoder = Encoder(
                enc_dim, dec_dim, self.enc_input_dim, self.embedding_layer,
                GRU_LSTM='LSTM', is_bidirectional=is_bidirectional)
            self.decoder = Decoder(enc_dim, dec_dim, self.dec_input_dim, enc_len,
                                   self.embedding_layer, self.attention_ind, GRU_LSTM='LSTM',
                                   is_bidirectional=is_bidirectional)

    def forward(self, one_batch):
        encoder_outputs, hidden = self.encoder(one_batch)

        y_pred = self.decoder(one_batch, encoder_outputs, hidden)

        return y_pred
