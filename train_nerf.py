"""Script to train a full NeRF model."""

from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
import json
import os

import fourier_feature_nets as ffn
import numpy as np
import torch


def _parse_args():
    parser = ArgumentParser("NeRF Training script",
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("data_path", help="Path to the data NPZ")
    parser.add_argument("results_dir", help="Path to output results")
    parser.add_argument("--mode",
                        choices=["rgba", "rgb", "dilate"],
                        default="rgba", help="Ray sampling mode.")
    parser.add_argument("--opacity-model",
                        help="Path to the optional opacity model")
    parser.add_argument("--num-samples", type=int, default=128,
                        help="Number of samples to take")
    parser.add_argument("--resolution", type=int, default=400,
                        help="Ray sampling resolution")
    parser.add_argument("--num-cameras", type=int, default=100,
                        help="Number of cameras")
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--num-layers", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=5e-4)
    parser.add_argument("--num-channels", type=int, default=256,
                        help="Number of channels in the MLP")
    parser.add_argument("--pos-freq", type=int, default=10,
                        help="Number of frequencies used for encoding")
    parser.add_argument("--pos-max-log-scale", type=float, default=9,
                        help="Value of sigma for the positional model")
    parser.add_argument("--view-freq", type=int, default=4,
                        help="Number of frequencies used for encoding")
    parser.add_argument("--view-max-log-scale", type=float, default=3,
                        help="Value of sigma for the positional model")
    parser.add_argument("--num-steps", type=int, default=50000,
                        help="Number of steps to use for training.")
    parser.add_argument("--report-interval", type=int, default=1000,
                        help="Interval for progress reports")
    parser.add_argument("--image-interval", type=int, default=2000,
                        help="Image rendering interval")
    parser.add_argument("--crop-steps", type=int, default=1000,
                        help="Number of steps to train on center crops")
    parser.add_argument("--seed", type=int, default=20080524,
                        help="Manual seed for the RNG")
    parser.add_argument("--omit-inputs", action="store_true",
                        help="Whether to omit inputs from the input vector")
    parser.add_argument("--decay-rate", type=float, default=0.1,
                        help="Rate at which the learning rate decays")
    parser.add_argument("--decay-steps", type=int, default=250000,
                        help="Interval over which the learning rate decays.")
    parser.add_argument("--weight-decay", type=float, default=0,
                        help="Regularizer term for the weights.")
    parser.add_argument("--make-video", action="store_true",
                        help="Whether to render frames for a training video.")
    parser.add_argument("--color-space", choices=["YCrCb", "RGB"],
                        default="RGB",
                        help="Color space to use during training.")
    parser.add_argument("--num-frames", type=int, default=200,
                        help="Number of frames in the training video orbit.")
    parser.add_argument("--device", default="cuda",
                        help="Pytorch compute device")
    return parser.parse_args()


def _main():
    args = _parse_args()

    torch.manual_seed(args.seed)
    model = ffn.NeRF(args.num_layers, args.num_channels,
                     args.pos_max_log_scale, args.pos_freq,
                     args.view_max_log_scale, args.view_freq,
                     [4], not args.omit_inputs)

    if args.opacity_model:
        opacity_model = ffn.load_model(args.opacity_model)
        if opacity_model is None:
            return 1

        opacity_model = opacity_model.to(args.device)
    else:
        opacity_model = None

    include_alpha = args.mode == "rgba"
    train_dataset = ffn.RayDataset.load(args.data_path, "train",
                                        args.num_samples, include_alpha,
                                        True, opacity_model,
                                        args.batch_size, args.color_space)
    val_dataset = ffn.RayDataset.load(args.data_path, "val",
                                      args.num_samples, include_alpha,
                                      False, opacity_model,
                                      args.batch_size, args.color_space)

    if train_dataset is None:
        return 1

    if args.make_video:
        cameras = ffn.orbit(np.array([0, 1, 0]), np.array([0, 0, -1]),
                            args.num_frames, 40,
                            train_dataset.resolution.square(), 4)
        bounds = np.eye(4, dtype=np.float32) * 2
        video_sampler = ffn.RaySampler(bounds, cameras, args.num_samples)
        image_interval = args.num_steps // args.num_frames
    else:
        video_sampler = None
        image_interval = args.image_interval

    if args.mode == "dilate":
        train_dataset.mode = ffn.RayDataset.Mode.Dilate

    raycaster = ffn.Raycaster(model)
    raycaster.to(args.device)

    log = raycaster.fit(train_dataset, val_dataset, args.results_dir,
                        args.batch_size, args.learning_rate,
                        args.num_steps, image_interval,
                        args.crop_steps, args.report_interval,
                        args.decay_rate, args.decay_steps,
                        args.weight_decay, video_sampler)

    model.save(os.path.join(args.results_dir, "nerf.pt"))

    with open(os.path.join(args.results_dir, "log.txt"), "w") as file:
        json.dump(vars(args), file)
        file.write("\n\n")
        file.write("\t".join(["step", "timestamp", "psnr_train", "psnr_val"]))
        file.write("\t")
        for line in log:
            file.write("\t".join([str(val) for val in line]) + "\n")

    sp_path = os.path.join(args.results_dir, "nerf.html")
    raycaster.to_scenepic(val_dataset).save_as_html(sp_path)


if __name__ == "__main__":
    _main()
