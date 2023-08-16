from typing import Optional, Union

import keras_cv
import numpy as np
import wandb
from tensorflow import data as tf_data
from tensorflow import keras
from tqdm.auto import tqdm

from .inference import get_mean_confidence_per_class


class WandBDetectionVisualizationCallback(keras.callbacks.Callback):
    def __init__(
        self,
        dataset: tf_data.Dataset,
        class_mapping: dict,
        max_batches_for_vis: Optional[Union[int, None]] = 1,
        iou_threshold: float = 0.01,
        confidence_threshold: float = 0.01,
        source_bounding_box_format: str = "xywh",
        title: str = "Evaluation-Table",
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.dataset = dataset.take(max_batches_for_vis)
        self.class_mapping = class_mapping
        self.max_batches_for_vis = max_batches_for_vis
        self.iou_threshold = iou_threshold
        self.confidence_threshold = confidence_threshold
        self.source_bounding_box_format = source_bounding_box_format
        self.title = title
        self.prediction_decoder = keras_cv.layers.MultiClassNonMaxSuppression(
            bounding_box_format=self.source_bounding_box_format,
            from_logits=True,
            iou_threshold=self.iou_threshold,
            confidence_threshold=self.confidence_threshold,
        )
        self.table = wandb.Table(columns=["Epoch", "Image", "Mean-Confidence"])

    def plot_prediction(self, epoch, image_batch, y_true_batch):
        y_pred_batch = self.model.predict(image_batch)
        y_pred = keras_cv.bounding_box.to_ragged(y_pred_batch)
        image_batch = keras_cv.utils.to_numpy(image_batch).astype(np.uint8)
        predicted_bounding_boxes = keras_cv.utils.to_numpy(
            keras_cv.bounding_box.convert_format(
                y_pred["boxes"],
                source=self.source_bounding_box_format,
                target="xyxy",
                images=image_batch,
            )
        )
        for idx in tqdm(range(image_batch.shape[0])):
            num_detections = y_pred["num_detections"][idx].item()
            predicted_boxes = predicted_bounding_boxes[idx][:num_detections]
            confidences = keras_cv.utils.to_numpy(
                y_pred["confidence"][idx][:num_detections]
            )
            classes = keras_cv.utils.to_numpy(y_pred["classes"][idx][:num_detections])
            wandb_prediction_boxes = []
            for box_idx in range(num_detections):
                wandb_prediction_boxes.append(
                    {
                        "position": {
                            "minX": predicted_boxes[box_idx][0]
                            / image_batch[idx].shape[0],
                            "minY": predicted_boxes[box_idx][1]
                            / image_batch[idx].shape[1],
                            "maxX": predicted_boxes[box_idx][2]
                            / image_batch[idx].shape[0],
                            "maxY": predicted_boxes[box_idx][3]
                            / image_batch[idx].shape[1],
                        },
                        "class_id": int(classes[box_idx]),
                        "box_caption": self.class_mapping[int(classes[box_idx])],
                        "scores": {"confidence": float(confidences[box_idx])},
                    }
                )
            wandb_image = wandb.Image(
                image_batch[idx],
                boxes={
                    "predictions": {
                        "box_data": wandb_prediction_boxes,
                        "class_labels": self.class_mapping,
                    },
                },
            )
            mean_confidence_dict = get_mean_confidence_per_class(
                confidences, classes, self.class_mapping
            )
            self.table.add_data(epoch, wandb_image, mean_confidence_dict)

    def on_epoch_end(self, epoch, logs):
        original_prediction_decoder = self.model._prediction_decoder
        self.model.prediction_decoder = self.prediction_decoder
        for _ in range(self.max_batches_for_vis):
            image_batch, y_true_batch = next(iter(self.dataset))
            self.plot_prediction(epoch, image_batch, y_true_batch)
        self.model.prediction_decoder = original_prediction_decoder

    def on_train_end(self, logs):
        wandb.log({self.title: self.table})
