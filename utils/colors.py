#!/usr/bin/env python3

import colorsys

from skimage import color
import numpy as np


def get_n_colors(n, ignore_colors=[]):
    ignore_colors = ignore_colors + [[0, 0, 0]]
    m = len(ignore_colors)
    n += m
    ignore_colors = color.rgb2lab(ignore_colors)

    colors = []
    for h in np.linspace(0, 1, 180, endpoint=False):
        for s in np.linspace(0.5, 1, 2):
            colors.append(np.array(colorsys.hls_to_rgb(h, 0.5, s)))
    colors = color.rgb2lab(colors)

    def initialize_centroids(points, n):
        centroids = points.copy()
        np.random.shuffle(centroids)
        if m:
            centroids[:m] = ignore_colors
        return centroids[:n]

    def closest_centroid(points, centroids):
        distances = np.sqrt(((points - centroids[:, np.newaxis]) ** 2).sum(axis=2))
        return np.argmin(distances, axis=0)

    def move_centroids(points, closest, centroids, n):
        return np.array([centroids[k] if k < m else points[closest == k].mean(axis=0) for k in range(n)])

    centroids = initialize_centroids(colors, n)

    for i in range(42):
        closest = closest_centroid(colors, centroids)
        new_centroids = move_centroids(colors, closest, centroids, n)
        diff = np.linalg.norm(centroids - new_centroids, axis=1).max()
        if diff < 1e-5:
            break
        centroids = new_centroids

    ret = []
    for lab in centroids[m:]:
        # print(lab, np.linalg.norm(ignore_colors - lab, axis=1).min())
        rgb = color.lab2rgb(lab)
        r, g, b = [int(round(x * 255)) for x in rgb]
        ret.append(f'#{r:02x}{g:02x}{b:02x}')

    return ret
