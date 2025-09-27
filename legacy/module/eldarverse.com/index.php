<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $contests_data = curlexec($URL, NULL, ['json_output' => true]);
    if (!is_array($contests_data) || !isset($contests_data["data"])) {
        trigger_error("Failed to retrieve contests data");
        return;
    }
    foreach ($contests_data["data"] as $contest_data) {
        $url = url_merge($URL, "/contest/{$contest_data['id']}");
        $title = 'EldarVerse | ' . $contest_data['name'] . " [" . $contest_data['type'] . "]";

        $contests[] = array(
            'start_time' => $contest_data['startTime'],
            'end_time' => $contest_data['endTime'],
            'title' => $title,
            'url' => $url,
            'key' => $contest_data['id'],
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
