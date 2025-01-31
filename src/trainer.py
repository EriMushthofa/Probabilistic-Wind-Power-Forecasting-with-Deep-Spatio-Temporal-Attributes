#!/usr/bin/env python

import torch
import torch.nn as nn
import numpy as np
from src.datamgr import wpDataset, NRELwpDataset
from torch.utils.data import DataLoader
from src.utils import cal_loss
from tqdm import tqdm

class EarlyStopping():
    def __init__(self, patience=10, min_delta=0):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_loss = None
        self.early_stop = False

    def __call__(self, val_loss):
        if self.best_loss == None:
            self.best_loss = val_loss
        elif self.best_loss - val_loss > self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
        elif self.best_loss - val_loss < self.min_delta:
            self.counter += 1
            print(
                f"INFO: Early stopping counter {self.counter} of {self.patience}")
            if self.counter >= self.patience:
                print('INFO: Early stopping')
                self.early_stop = True


class Trainer:
    def __init__(self, model, data_mgr, optimizer, criterion, SAVE_FILE,
                 BATCH_SIZE, ENC_LEN=48, DEC_LEN=12, name='wind_power'):
        self.model = model
        self.name = name
        if name == 'wind_power':
            train_dataset = wpDataset(
                data_mgr.train_data, ENC_LEN=ENC_LEN, DEC_LEN=DEC_LEN)
            val_dataset = wpDataset(
                data_mgr.val_data, ENC_LEN=ENC_LEN, DEC_LEN=DEC_LEN)
            test_dataset = wpDataset(
                data_mgr.test_data, ENC_LEN=ENC_LEN, DEC_LEN=DEC_LEN)
        else:
            train_dataset = NRELwpDataset(
                data_mgr.train_data, ENC_LEN=ENC_LEN, DEC_LEN=DEC_LEN)
            val_dataset = NRELwpDataset(
                data_mgr.val_data, ENC_LEN=ENC_LEN, DEC_LEN=DEC_LEN)
            test_dataset = NRELwpDataset(
                data_mgr.test_data, ENC_LEN=ENC_LEN, DEC_LEN=DEC_LEN)
        train_dataloader = DataLoader(train_dataset, batch_size=BATCH_SIZE)
        val_dataloader = DataLoader(val_dataset, batch_size=BATCH_SIZE)
        test_dataloader = DataLoader(test_dataset, batch_size=BATCH_SIZE)

        self.train_dataloader = train_dataloader
        self.val_dataloader = val_dataloader
        self.test_dataloader = test_dataloader

        self.train_dataset = train_dataset
        self.val_dataset = val_dataset
        self.test_dataset = test_dataset

        self.optimizer = optimizer
        self.criterion = criterion

        self.SAVE_FILE = SAVE_FILE

    def train(self, epochs):
        early_stopping = EarlyStopping()
        for epoch in range(epochs):
            print(' ')
            print(f"Epoch {epoch+1} of {epochs}")
            train_loss, train_mae, train_rmse = self.fit()
            print(f'Train Loss: {train_loss:.4f}')
            print(f'Train MAE: {np.array(train_mae).reshape(2,6)}')
            print(f'Train RMSE: {np.array(train_rmse).reshape(2,6)}')

            val_loss, val_mae, val_rmse = self.validate()
            print(f'Val Loss: {val_loss:.4f}')
            print(f'Val MAE: {np.array(val_mae).reshape(2,6)}')
            print(f'Val RMSE: {np.array(val_rmse).reshape(2,6)}')

            early_stopping(val_loss)
            print(f'Best Val Loss: {early_stopping.best_loss:.4f}')

            if early_stopping.early_stop:
                torch.save(self.model.state_dict(), 'outputs/'+self.SAVE_FILE+'.pt')
                break
        else:
            torch.save(self.model.state_dict(), 'outputs/'+self.SAVE_FILE+'.pt')
        return train_loss, train_mae, train_rmse


    def fit(self):
        print('Training')
        self.model.train()
        counter = 0
        running_loss = 0.
        running_mae = [0.] * 12
        running_rmse = [0.] * 12
        prog_bar = tqdm(enumerate(self.train_dataloader), total=int(
            len(self.train_dataset)/self.train_dataloader.batch_size))
        for i, data in prog_bar:
            counter += 1
            self.optimizer.zero_grad()
            y_pred = self.model(data)
            y_true = data[2]
            y_true = y_true[:, 1:, 0]
            y_pred = y_pred.permute(1, 0)
            mae, rmse = cal_loss(y_true, y_pred, self.name)

            y_true, y_pred = self.rescale_output(y_true, y_pred)

            idx = ~torch.isnan(y_true)
            loss = self.criterion(y_pred[idx], y_true[idx])
            running_loss += loss.item()
            loss.backward()
            self.optimizer.step()

            running_mae = [x+y for x, y in zip(running_mae, mae)]
            running_rmse = [x+y for x, y in zip(running_rmse, rmse)]

        train_loss = running_loss / counter
        train_mae = [x / counter for x in running_mae]
        train_rmse = [x / counter for x in running_rmse]

        return train_loss, train_mae, train_rmse

    def validate(self):
        print('Validating')
        self.model.eval()
        counter = 0
        running_loss = 0.
        running_mae = [0.] * 12
        running_rmse = [0.] * 12

        prog_bar = tqdm(enumerate(self.val_dataloader), total=int(
            len(self.val_dataset)/self.val_dataloader.batch_size))
        with torch.no_grad():
            for i, data in prog_bar:
                counter += 1
                y_pred = self.model(data)
                y_true = data[2]
                y_true = y_true[:, 1:, 0]
                y_pred = y_pred.permute(1, 0)
                mae, rmse = cal_loss(y_true, y_pred, self.name)

                y_true, y_pred = self.rescale_output(y_true, y_pred)

                idx = ~torch.isnan(y_true)
                loss = self.criterion(y_pred[idx], y_true[idx])
                running_loss += loss.item()

                running_mae = [x+y for x, y in zip(running_mae, mae)]
                running_rmse = [x+y for x, y in zip(running_rmse, rmse)]

            val_loss = running_loss / counter
            val_mae = [x / counter for x in running_mae]
            val_rmse = [x / counter for x in running_rmse]

        return val_loss, val_mae, val_rmse

    def report_test_error(self):
        print('Calculating Test Error')
        self.model.eval()
        counter = 0
        running_loss = 0.
        running_mae = [0.] * 12
        running_rmse = [0.] * 12

        # Enable dropout for inference (Monte Carlo Dropout)
        def apply_dropout(m):
            if type(m) == nn.Dropout:
                m.train()
        self.model.apply(apply_dropout)
        num_samples = 10  # Number of Monte Carlo samples
        total_percentage_diff = 0
        total_count = 0

        all_y_true = []
        all_y_pred = []


        prog_bar = tqdm(enumerate(self.test_dataloader), total=int(
            len(self.test_dataset)/self.test_dataloader.batch_size))

        with torch.no_grad():
            for i, data in prog_bar:
                counter += 1
                # Monte Carlo predictions
                mc_predictions = []
                for _ in range(num_samples):
                    mc_pred = self.model(data)
                    mc_predictions.append(mc_pred)

                stacked_predictions = torch.stack(mc_predictions)
                mean_prediction = stacked_predictions.mean(0)
                mean_prediction = mean_prediction.permute(1, 0)

                y_true = data[2]
                y_true = y_true[:, 1:, 0]

                mae, rmse = cal_loss(y_true, mean_prediction, self.name)

                y_true, mean_prediction = self.rescale_output(y_true, mean_prediction)
                idx = ~torch.isnan(y_true)

                all_y_true.append(y_true)
                all_y_pred.append(mean_prediction)

                loss = self.criterion(mean_prediction[idx], y_true[idx])
                running_loss += loss.item()

                running_mae = [x + y for x, y in zip(running_mae, mae)]
                running_rmse = [x + y for x, y in zip(running_rmse, rmse)]

                # Calculate percentage difference
                percentage_diff = ((y_true - mean_prediction) / y_true) * 100
                valid_percentage_diff = percentage_diff[~torch.isnan(percentage_diff)]
                total_percentage_diff += valid_percentage_diff.sum()
                total_count += valid_percentage_diff.numel()

        y_true_concat = torch.cat(all_y_true, dim=0)
        y_pred_concat = torch.cat(all_y_pred, dim=0)
        test_loss = running_loss/counter
        test_mae = [x / counter for x in running_mae]
        test_rmse = [x / counter for x in running_rmse]
        average_percentage_diff = total_percentage_diff / total_count

        print(f'Test Loss: {test_loss:.4f}')
        print(f'Test MAE: {np.array(test_mae).reshape(2,6)}')
        print(f'Test RMSE: {np.array(test_rmse).reshape(2,6)}')
        print(f'Average Percentage Difference: {average_percentage_diff:.2f}%')



        return test_loss, test_mae, test_rmse, average_percentage_diff, y_true_concat, y_pred_concat

    def rescale_output(self, y_true, y_pred):
        for i in range(12):
            y_true[:, i] = y_true[:, i] * np.sqrt(12-i)
            y_pred[:, i] = y_pred[:, i] * np.sqrt(12-i)

        return y_true, y_pred
