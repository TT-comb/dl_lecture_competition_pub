# ライブラリのインポート
import re # 正規表現(regular expression)パターンによる処理を行うためのライブラリ
import random
import time
from statistics import mode

from PIL import Image
import numpy as np
import pandas
import torch
import torch.nn as nn
import torchvision
from torchvision import transforms

# 関数1 set_seed(seed)
def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

# 関数2 process_text(text) # outputは処理を経た文字列としてのtext
def process_text(text):
    # lowercase
    text = text.lower() # 文字列textを小文字にする

    # 数詞を数字に変換
    num_word_to_digit = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
        'ten': '10'
    }
    for word, digit in num_word_to_digit.items():
        text = text.replace(word, digit)

    # 小数点のピリオドを削除 # 小数点のピリオドが消えない????
    text = re.sub(r'(?<!\d)\.(?!\d)', '', text)

    # 冠詞の削除
    text = re.sub(r'\b(a|an|the)\b', '', text)

    # 短縮形のカンマの追加
    contractions = {
        "dont": "don't", "isnt": "isn't", "arent": "aren't", "wont": "won't",
        "cant": "can't", "wouldnt": "wouldn't", "couldnt": "couldn't"
    }
    for contraction, correct in contractions.items():
        text = text.replace(contraction, correct)

    # 句読点をスペースに変換
    text = re.sub(r"[^\w\s':]", ' ', text)

    # 句読点をスペースに変換
    text = re.sub(r'\s+,', ',', text)

    # 連続するスペースを1つに変換
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# 1. データローダーの作成 # クラス1 VQADataset(torch.utils.data.Dataset) # __init__ # update_dict # __getitem__ # __len__
class VQADataset(torch.utils.data.Dataset):
    def __init__(self, df_path, image_dir, transform=None, answer=True):
        self.transform = transform  # 画像の前処理
        self.image_dir = image_dir  # 画像ファイルのディレクトリ
        self.df = pandas.read_json(df_path)  # 画像ファイルのパス，question, answerを持つDataFrame # df["question"], df["answers"]
        self.answer = answer

        # question / answerの辞書を作成
        self.question2idx = {} # questionをid化 # 全てのquestionをひとまとめに
        self.answer2idx = {} # answerをid化 # 全てのanswerをひとまとめに
        self.idx2question = {} # idをquestionに変換
        self.idx2answer = {} # idをanswerに変換

        # 質問文に含まれる単語を辞書に追加
        for question in self.df["question"]:
            question = process_text(question) # process_text()を使用
            words = question.split(" ")
            for word in words:
                if word not in self.question2idx:
                    self.question2idx[word] = len(self.question2idx) # 各単語のidを作っている
        self.idx2question = {v: k for k, v in self.question2idx.items()}  # 逆変換用の辞書(question) # {id1: word1, id2: word2, ...}という辞書を作成
        # print(self.question2idx) # for check
        # print('yes!') # for check
        if self.answer: # __init__の入力で answer=Trueとしている
            # 回答に含まれる単語を辞書に追加
            for answers in self.df["answers"]:
                for answer in answers:
                    word = answer["answer"]
                    word = process_text(word) # process_text()を使用
                    if word not in self.answer2idx:
                        self.answer2idx[word] = len(self.answer2idx) # 各単語のidを作っている
            # self.idx2answer = {v: k for k, v in self.answer2idx.items()}  # 逆変換用の辞書(answer) # {id1: word1, id2: word2, ...}という辞書を作成
            # print(self.answer2idx) # for check

            # 回答に含まれる単語を辞書に追加
            class_mapping = pandas.read_csv("/content/drive/MyDrive/VQA/dl_lecture_competition_pub/class_mapping.csv")
            # class_mapping = pandas.read_csv("/content/data/class_mapping.csv")
            for i in range(len(class_mapping)): 
              if class_mapping.iloc[i, 0] not in self.answer2idx: 
                self.answer2idx[class_mapping.iloc[i, 0]] = class_mapping.iloc[i, 1]+len(self.answer2idx)
            # print(self.answer2idx) # for check
            self.idx2answer = {v: k for k, v in self.answer2idx.items()}  # 逆変換用の辞書(answer) # {id1: word1, id2: word2, ...}という辞書を作成
            # print(self.answer2idx) # for check

    def update_dict(self, dataset): # ?? 何のために？
        """
        検証用データ，テストデータの辞書を訓練データの辞書に更新する．

        Parameters
        ----------
        dataset : Dataset
            訓練データのDataset
        """
        self.question2idx = dataset.question2idx
        self.answer2idx = dataset.answer2idx
        self.idx2question = dataset.idx2question
        self.idx2answer = dataset.idx2answer

    def __getitem__(self, idx):
        """
        対応するidxのデータ（画像，質問，回答）を取得．

        Parameters
        ----------
        idx : int
            取得するデータのインデックス

        Returns (括弧の中身は, データのsize)
        -------
        image : torch.Tensor  (C, H, W)
            画像データ
        question : torch.Tensor  (vocab_size)
            質問文をone-hot表現に変換したもの
        answers : torch.Tensor  (n_answer)
            10人の回答者の回答のid
        mode_answer_idx : torch.Tensor  (1)
            10人の回答者の回答の中で最頻値の回答のid
        """
        image = Image.open(f"{self.image_dir}/{self.df['image'][idx]}")
        image = self.transform(image)
        question = np.zeros(len(self.idx2question) + 1)  # 未知語用の要素を追加
        question_words = self.df["question"][idx].split(" ")
        for word in question_words:
            try:
                question[self.question2idx[word]] = 1  # one-hot表現に変換 (# idは, 0以上len(idx2question)-1以下の整数)
            except KeyError:
                question[-1] = 1  # 未知語
        
        '''if self.answer:
          answers = []
          for answer in self.df["answers"][idx]: 
            if answer["answer_confidence"] == "yes": 
              answers.append(self.answer2idx[process_text(answer["answer"])])
          mode_answer_idx = mode(answers)  # 最頻値を取得（正解ラベル） # 10個のidの最頻値を取得
            # print(mode_answer_idx) # for check

          return image, torch.Tensor(question), torch.Tensor(answers), int(mode_answer_idx)'''

        if self.answer:
            answers = [self.answer2idx[process_text(answer["answer"])] for answer in self.df["answers"][idx]] # 要素数10の配列, 各要素がidx(辞書answer2idxのvalue)
            mode_answer_idx = mode(answers)  # 最頻値を取得（正解ラベル） # 10個のidの最頻値を取得
            # print(mode_answer_idx) # for check

            return image, torch.Tensor(question), torch.Tensor(answers), int(mode_answer_idx)

        else:
          return image, torch.Tensor(question)

    def __len__(self):
        return len(self.df)


# 2. 評価指標の実装 # 関数3 VQA_criterion(batch_pred: torch.Tensor, batch_answers: torch.Tensor)
# 簡単にするならBCEを利用する
def VQA_criterion(batch_pred: torch.Tensor, batch_answers: torch.Tensor): # 引数の後のコロンは、関数アノテーションの1種(引数: 期待する型)
    total_acc = 0.

    for pred, answers in zip(batch_pred, batch_answers):
        acc = 0.
        for i in range(len(answers)):
            num_match = 0
            for j in range(len(answers)):
                if i == j:
                    continue
                if pred == answers[j]:
                    num_match += 1
            acc += min(num_match / 3, 1)
        total_acc += acc / 10

    return total_acc / len(batch_pred)


# 3. モデルの実装 # クラス2 Basic Block(nn.Module) # __init__ # forward
# ResNetを利用できるようにしておく
class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()

        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=stride, padding=1)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.relu = nn.ReLU(inplace=True)

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, kernel_size=1, stride=stride),
                nn.BatchNorm2d(out_channels)
            )

    def forward(self, x):
        residual = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))

        out += self.shortcut(residual)
        out = self.relu(out)

        return out


class BottleneckBlock(nn.Module): # クラス3 BottleneckBlock(nn.Module) # __init__ # forward
    expansion = 4

    def __init__(self, in_channels: int, out_channels: int, stride: int = 1):
        super().__init__()

        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size=1, stride=1)
        self.bn1 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=stride, padding=1)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.conv3 = nn.Conv2d(out_channels, out_channels * self.expansion, kernel_size=1, stride=1)
        self.bn3 = nn.BatchNorm2d(out_channels * self.expansion)
        self.relu = nn.ReLU(inplace=True)

        self.shortcut = nn.Sequential()
        if stride != 1 or in_channels != out_channels * self.expansion:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_channels, out_channels * self.expansion, kernel_size=1, stride=stride),
                nn.BatchNorm2d(out_channels * self.expansion)
            )

    def forward(self, x):
        residual = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))

        out += self.shortcut(residual)
        out = self.relu(out)

        return out


class ResNet(nn.Module): # クラス4  ResNet(nn.Module) # __init__ # _make_layer # forward
    def __init__(self, block, layers):
        super().__init__()
        self.in_channels = 64

        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        self.layer1 = self._make_layer(block, layers[0], 64)
        self.layer2 = self._make_layer(block, layers[1], 128, stride=2)
        self.layer3 = self._make_layer(block, layers[2], 256, stride=2)
        self.layer4 = self._make_layer(block, layers[3], 512, stride=2)

        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(512 * block.expansion, 512)

    def _make_layer(self, block, blocks, out_channels, stride=1):
        layers = []
        layers.append(block(self.in_channels, out_channels, stride))
        self.in_channels = out_channels * block.expansion
        for _ in range(1, blocks):
            layers.append(block(self.in_channels, out_channels))

        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.relu(self.bn1(self.conv1(x)))
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        x = self.avgpool(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x)

        return x


def ResNet18(): # 関数4 ResNet18
    return ResNet(BasicBlock, [2, 2, 2, 2])


def ResNet50(): # 関数5 ResNet50
    return ResNet(BottleneckBlock, [3, 4, 6, 3])


class VQAModel(nn.Module): # クラス5 VQAModel(nn.Module)
    def __init__(self, vocab_size: int, n_answer: int):
        super().__init__()
        self.resnet = ResNet18()
        self.text_encoder = nn.Linear(vocab_size, 512)

        self.fc = nn.Sequential(
            nn.Linear(1024, 512),
            nn.ReLU(inplace=True),
            nn.Linear(512, n_answer)
        )

    def forward(self, image, question):
        image_feature = self.resnet(image)  # 画像の特徴量
        question_feature = self.text_encoder(question)  # テキストの特徴量

        x = torch.cat([image_feature, question_feature], dim=1)
        x = self.fc(x)

        return x


# 4. 学習の実装 # 関数6 train(model, dataloader, optimizer, criterion, device)
def train(model, dataloader, optimizer, criterion, device):
    model.train()
    # print('pass4.1') # for check
    total_loss = 0
    total_acc = 0
    simple_acc = 0

    start = time.time()
    for image, question, answers, mode_answer in dataloader:
        image, question, answer, mode_answer = \
            image.to(device), question.to(device), answers.to(device), mode_answer.to(device)
        # print('pass4.2') # for check
        pred = model(image, question)
        loss = criterion(pred, mode_answer.squeeze())
        # print('pass4.3') # for check
        optimizer.zero_grad()
        # print('pass4.3.1') # for check
        loss.backward() # エラーの原因
        # print('pass4.3.2') # for check
        optimizer.step()
        # print('pass4.4') # for check
        total_loss += loss.item()
        total_acc += VQA_criterion(pred.argmax(1), answers)  # VQA accuracy
        simple_acc += (pred.argmax(1) == mode_answer).float().mean().item()  # simple accuracy
        # print('pass4.5') # for check
    return total_loss / len(dataloader), total_acc / len(dataloader), simple_acc / len(dataloader), time.time() - start


# 関数7 eval(model, dataloader, optimizer, criterion, device)
def eval(model, dataloader, optimizer, criterion, device):
    model.eval()

    total_loss = 0
    total_acc = 0
    simple_acc = 0

    start = time.time()
    for image, question, answers, mode_answer in dataloader:
        image, question, answer, mode_answer = \
            image.to(device), question.to(device), answers.to(device), mode_answer.to(device)

        pred = model(image, question)
        loss = criterion(pred, mode_answer.squeeze())

        total_loss += loss.item()
        total_acc += VQA_criterion(pred.argmax(1), answers)  # VQA accuracy
        simple_acc += (pred.argmax(1) == mode_answer).mean().item()  # simple accuracy

    return total_loss / len(dataloader), total_acc / len(dataloader), simple_acc / len(dataloader), time.time() - start

# 関数8 main()
def main():
    # deviceの設定
    set_seed(42) # 関数1
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # dataloader / model
    transform = transforms.Compose([
        transforms.Resize((224, 224)), # デフォルトのデータ拡張
        transforms.ToTensor()
    ])

    '''transform = transforms.Compose([
        transforms.Resize((224, 224)), # デフォルトのデータ拡張
        transforms.ToTensor(),
        transforms.RandomErasing(p=0.8, scale=(0.02, 0.33), ratio=(0.3, 3.3)),
        ]) # random erasing'''

    # train_dataset = VQADataset(df_path="./data/train.json", image_dir="./data/train", transform=transform)
    # test_dataset = VQADataset(df_path="./data/valid.json", image_dir="./data/valid", transform=transform, answer=False)
    train_dataset = VQADataset(df_path="/content/data/train.json", image_dir="/content/data/train", transform=transform) # クラス1 # answer=True(デフォルト)
    test_dataset = VQADataset(df_path="/content/data/valid.json", image_dir="/content/data/valid", transform=transform, answer=False) # クラス1
    test_dataset.update_dict(train_dataset) # クラス1のメソッド
    # print('pass 1') # for check

    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=128, shuffle=True) # Dataloader: datasetsからバッチごとに取り出す
    test_loader = torch.utils.data.DataLoader(test_dataset, batch_size=1, shuffle=False) # Dataloader: datasetsからバッチごとに取り出す
    # print('pass 2') # for check
    model = VQAModel(vocab_size=len(train_dataset.question2idx)+1, n_answer=len(train_dataset.answer2idx)).to(device) # クラス5
    # print('pass 3') # for check
    # optimizer / criterion
    num_epoch = 10
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
    # print('pass 4') # for check
    # train model
    for epoch in range(num_epoch):
        train_loss, train_acc, train_simple_acc, train_time = train(model, train_loader, optimizer, criterion, device) # 関数6
        print(f"【{epoch + 1}/{num_epoch}】\n"
              f"train time: {train_time:.2f} [s]\n"
              f"train loss: {train_loss:.4f}\n"
              f"train acc: {train_acc:.4f}\n"
              f"train simple acc: {train_simple_acc:.4f}")
    # print('pass 5') # for check
    # 提出用ファイルの作成
    model.eval() # 関数7
    submission = []
    for image, question in test_loader:
        image, question = image.to(device), question.to(device)
        pred = model(image, question)
        pred = pred.argmax(1).cpu().item()
        submission.append(pred)

    submission = [train_dataset.idx2answer[id] for id in submission]
    submission = np.array(submission)
    torch.save(model.state_dict(), "model.pth")
    np.save("submission.npy", submission)

if __name__ == "__main__": # コマンドラインから実行した時(!python main.py)にTrueとなる
    main() # 関数8
