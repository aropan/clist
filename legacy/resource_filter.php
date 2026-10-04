<?php

function normalize_resource_ids($values): array
{
    if (!is_array($values)) {
        return [-1];
    }

    $ids = [];
    foreach ($values as $value) {
        if (!is_int($value) && !is_string($value)) {
            continue;
        }
        $id = filter_var($value, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 2147483647]]);
        if ($id !== false) {
            $ids[$id] = $id;
        }
    }
    return $ids ? array_values($ids) : [-1];
}

function resource_ids_from_cookie($cookie): array
{
    if (!is_string($cookie)) {
        return [-1];
    }
    // Preserve existing serialized preferences without instantiating cookie-supplied objects.
    $values = @unserialize($cookie, ['allowed_classes' => false, 'max_depth' => 2]);
    return normalize_resource_ids($values);
}
