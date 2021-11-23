import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Input, \
                                    Conv2D, \
                                    MaxPooling2D, \
                                    Concatenate, \
                                    UpSampling2D, \
                                    BatchNormalization, \
                                    Activation, \
                                    Conv2DTranspose
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.optimizers.schedules import ExponentialDecay
from tensorflow.keras.callbacks import ModelCheckpoint, TensorBoard

import os
import pickle
import datetime
from config import Config
from model.base_model import BaseModel
from dataloader.data_loader import DataLoader
from utils.plot_utils import PlotUtils


class UNet(BaseModel):

    def __init__(self):

        super().__init__()

        # Data and its attributes
        self.train_input = None
        self.train_output = None
        self.test_input = None
        self.test_output = None
        self.data_generator = ImageDataGenerator(validation_split=Config.config["train"]["validation_split"])

        # Model and its attributes
        self.model_path = Config.config["model"]["model_path"]
        self.experiment_name = Config.config["model"]["experiment_name"]
        self.model = None
        self.checkpoint_callback = None
        self.tensorboard_callback = None

        # Training
        self.epochs = Config.config["train"]["epochs"]
        self.train_batch_size = Config.config["train"]["train_batch_size"]
        self.val_batch_size = Config.config["train"]["val_batch_size"]

    def load_data(self, show_data=False):
        self.train_input, self.train_output, self.test_input, self.test_output = DataLoader().main(show_data)

    def build(self):

        def _one_cnn_layer(input, num_filters, kernel_size, padding):
            layer = Conv2D(num_filters, kernel_size=kernel_size, padding=padding)(input)
            layer = BatchNormalization()(layer)
            layer = Activation("relu")(layer)
            return layer

        def _create_model():
            input_layer = Input(shape=(50, 50, 2))

            """ Down-sampling """

            conv1 = _one_cnn_layer(input_layer, 64, 3, "VALID")
            conv1 = _one_cnn_layer(conv1, 64, 3, "SAME")
            conv1 = _one_cnn_layer(conv1, 64, 3, "SAME")
            pool1 = MaxPooling2D(pool_size=2)(conv1)  # 24 x 24

            conv2 = _one_cnn_layer(pool1, 128, 3, "SAME")
            conv2 = _one_cnn_layer(conv2, 128, 3, "SAME")
            conv2 = _one_cnn_layer(conv2, 128, 3, "SAME")
            pool2 = MaxPooling2D(pool_size=2)(conv2)  # 12 x 12

            conv3 = _one_cnn_layer(pool2, 256, 3, "SAME")
            conv3 = _one_cnn_layer(conv3, 256, 3, "SAME")
            conv3 = _one_cnn_layer(conv3, 256, 3, "SAME")
            pool3 = MaxPooling2D(pool_size=2)(conv3)  # 6 x 6

            conv4 = _one_cnn_layer(pool3, 512, 3, "SAME")
            conv4 = _one_cnn_layer(conv4, 512, 3, "SAME")
            conv4 = _one_cnn_layer(conv4, 512, 3, "SAME")

            """ Up-sampling """

            up5 = (UpSampling2D(size=(2, 2))(conv4))  # 12 x 12
            merge5 = Concatenate()([conv3, up5])

            conv5 = _one_cnn_layer(merge5, 256, 2, "SAME")
            conv5 = _one_cnn_layer(conv5, 256, 3, "SAME")
            conv5 = _one_cnn_layer(conv5, 256, 3, "SAME")

            up6 = (UpSampling2D(size=(2, 2))(conv5))  # 24 x 24
            merge6 = Concatenate()([conv2, up6])

            conv6 = _one_cnn_layer(merge6, 128, 2, "SAME")
            conv6 = _one_cnn_layer(conv6, 128, 3, "SAME")
            conv6 = _one_cnn_layer(conv6, 128, 3, "SAME")

            up7 = (UpSampling2D(size=(2, 2))(conv6))  # 48 x 48
            merge7 = Concatenate()([conv1, up7])

            conv7 = _one_cnn_layer(merge7, 64, 2, "SAME")
            conv7 = _one_cnn_layer(conv7, 64, 3, "SAME")
            conv7 = _one_cnn_layer(conv7, 64, 3, "SAME")

            conv8 = Conv2DTranspose(1, kernel_size=3, padding="VALID")(conv7)  # 50 x 50
            merge9 = Concatenate()([input_layer, conv8])

            """ Final layer """
            conv10 = Conv2D(1, kernel_size=1)(merge9)
            conv10 = Activation("relu")(conv10)

            model = Model(inputs=input_layer, outputs=conv10)
            return model

        self.model = _create_model()
        lr_schedule = ExponentialDecay(Config.config["train"]["initial_learning_rate"],
                                       decay_steps=Config.config["train"]["decay_steps"],
                                       decay_rate=Config.config["train"]["decay_rate"])
        self.model.compile(optimizer=Adam(learning_rate=lr_schedule), loss="mean_absolute_error", metrics=["accuracy"])

    def checkpoint(self):
        filepath = os.path.join(self.model_path,
                                self.experiment_name,
                                "checkpoints",
                                "weights-{epoch:02d}-{loss:.4f}-{val_loss:.4f}")

        self.checkpoint_callback = ModelCheckpoint(filepath,
                                                   monitor='val_loss',
                                                   verbose=0,
                                                   save_best_only=True,
                                                   save_weights_only=False,
                                                   mode='auto',
                                                   save_freq="epoch",
                                                   period=1)

    def tensorboard(self):
        log_dir = os.path.join(self.model_path,
                               "logs",
                               self.experiment_name,
                               datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        file_writer = tf.summary.create_file_writer(log_dir)
        file_writer.set_as_default()
        self.tensorboard_callback = TensorBoard(log_dir=log_dir,
                                                histogram_freq=1)

    def train(self):
        model_history = self.model.fit(self.data_generator.flow(self.train_input,
                                                                self.train_output,
                                                                batch_size=self.train_batch_size,
                                                                subset='training'),
                                       validation_data=self.data_generator.flow(self.train_input,
                                                                                self.train_output,
                                                                                batch_size=self.val_batch_size,
                                                                                subset='validation'),
                                       steps_per_epoch=len(self.train_input) / (self.train_batch_size + self.val_batch_size),
                                       shuffle=True,
                                       epochs=self.epochs,
                                       callbacks=[self.checkpoint_callback,
                                                  self.tensorboard_callback])
        with open(os.path.join(self.model_path, self.experiment_name, "model_history.pkl")) as f:
            pickle.dump(f, model_history)

    def evaluate(self):
        pred_output = self.model.predict(self.test_input)
        PlotUtils.plot_results(self.test_output, self.test_input, pred_output)
