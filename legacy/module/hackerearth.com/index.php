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
        $en_url = preg_replace('#hackerearth.com/(ru|en-us/)?#', 'hackerearth.com/en-us/', $url);
        $url = str_replace('/ru/', '/', $url);

        if (!preg_match('#/([^/]*)/?$#', $url, $match)) {
            trigger_error("No set id for event '$title', url = '$url'", E_USER_WARNING);
            continue;
        }
        $key = $match[1];
        $is_sprint_key = strpos($url, '/sprints/') !== false;
        $contest_page = curlexec($en_url);

        $info = array();
        if (preg_match('#<h1[^>]*class="event-[^"]*"[^>]*>(?:[^<]*<[^/][^>]*>[^<]*)<i[^>]*class="[^"]*fa-star[^"]*"[^>]*>[^<]*</i>(?P<label>[^<]*)#', $contest_page, $match)) {
            $label = trim($match['label']);
            $label = ucfirst(strtolower($label));
            $title .= ". " . $label;
            $info['_no_update_account_time'] = stripos($label, 'rated') === false;
        } else {
            $info['_no_update_account_time'] = true;
        }

        if (preg_match_all('#<div[^>]*time-location[^>]*>\s*<div[^>]*location[^>]*>.*?(?:\s*</div[^>]*>){3}#sm', $contest_page, $matches)) {
            foreach ($matches[0] as $page) {
                preg_match_all('#>\s*(\w[^<]*?)\s*<#', $page, $ms);
                $ms = $ms[1];
                $start_idx = -1;
                $end_idx = -1;
                foreach ($ms as $i => $v) {
                    if (in_array($v, array('starts on:', 'opens at:'))) {
                        $start_idx = $start_idx == -1? $i : -2;
                    }
                    if (in_array($v, array('ends on:', 'closes on:'))) {
                        $end_idx = $end_idx == -1? $i : -2;
                    }
                }
                if ($start_idx < 2 || $end_idx < 2 || count($ms) != 6) {
                    trigger_error("No match time location '$title', url = '$url'", E_USER_WARNING);
                    continue;
                }
                $t = implode('. ', array($title, ucfirst($ms[0]), $ms[1]));
                $k = $key;
                if (count($matches[0]) > 1) {
                    $k .= "\n$t";
                }
                $contests[] = array(
                    'start_time' => $ms[$start_idx + 1],
                    'end_time' => $ms[$end_idx + 1],
                    'title' => $t,
                    'url' => $url,
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => 'UTC',
                    'info' => $info,
                    'key' => $k,
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
                'info' => $info,
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
