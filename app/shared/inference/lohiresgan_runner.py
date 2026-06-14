import os

import cv2
import nibabel as nib
import numpy as np

_model = None
_model_dir = None


def run_lohiresgan(input_path, output_path, model_dir):
    global _model, _model_dir
    import tensorflow as tf

    if _model is None or _model_dir != model_dir:
        _model = tf.keras.models.load_model(model_dir)
        _model_dir = model_dir

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    input_image = nib.load(input_path)
    input_data = input_image.get_fdata()

    normalized_arr = 2 * (input_data - input_data.min()) / (input_data.max() - input_data.min()) - 1
    output_data = np.zeros_like(input_data)
    X = input_data.shape[0]
    Y = input_data.shape[1]

    # Iterate through each slice — resize, pass through model, resize back, save to output array
    for i in range(normalized_arr.shape[2]):
        slice_data = normalized_arr[:, :, i]
        resized_img = cv2.resize(slice_data, (256, 256), interpolation=cv2.INTER_CUBIC)
        resized_slice_data = np.expand_dims(resized_img, -1)
        resized_slice_data = np.expand_dims(resized_slice_data, -0)
        gen_image = _model.predict(resized_slice_data)
        gen_image = np.squeeze(gen_image, axis=0)
        gen_image = np.squeeze(gen_image, axis=-1)
        rescaled_arr = (gen_image + 1) * 127.5
        rescaled_arr = rescaled_arr.astype("float64")
        resized_slice_data_final = cv2.resize(rescaled_arr, (Y, X), interpolation=cv2.INTER_CUBIC)
        output_data[:, :, i] = resized_slice_data_final

    output_image = nib.Nifti1Image(output_data, input_image.affine, header=input_image.header)
    nib.save(output_image, output_path)
    return output_path
