<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $data = curlexec($URL, NULL, array('json_output' => 1));
    if (!isset($data['response'])) {
        print_r($data);
        return;
    }
    $data = $data['response'];
    foreach ($data as $item) {
        $title = $item['title'];

        $url = $item['url'];
        $url = str_replace('/ru/', '/', $url);

        if (!preg_match('#/([^/]*)/?$#', $url, $match)) {
            trigger_error("No set id for event '$title', url = '$url'", E_USER_WARNING);
            continue;
        }
        $key = $match[1];
        $is_sprint_key = strpos($url, '/sprints/') !== false;
        if ($is_sprint_key && preg_match_all('#<div[^>]*time-location[^>]*>\s*<div[^>]*location[^>]*>.*?(?:\s*</div[^>]*>){3}#sm', curlexec($url), $matches)) {
            foreach ($matches[0] as $page) {
                preg_match_all('#>\s*(\w[^<]*?)\s*<#', $page, $ms);
                $ms = $ms[1];
                if (count($ms) !== 6 || $ms[2] !== 'opens at:' || $ms[4] != 'closes on:') {
                    print_r($ms);
                    trigger_error("No match time location '$title', url = '$url'", E_USER_WARNING);
                    continue;
                }
                $t = implode('. ', array($title, ucfirst($ms[0]), $ms[1]));
                $contests[] = array(
                    'start_time' => $ms[3],
                    'end_time' => $ms[5],
                    'title' => $t,
                    'url' => $url,
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => 'UTC',
                    'key' => $key . '\n' . $t,
                );
            }
        } else {
            $contests[] = array(
                'start_time' => $item['start_tz'],
                'end_time' => $item['end_tz'],
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => 'UTC',
                'key' => $key,
            );
            if ($is_sprint_key) {
                trigger_error("No find time location block '$title', url = '$url'", E_USER_WARNING);
            }
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
