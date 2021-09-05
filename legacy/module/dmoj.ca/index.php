<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $prefix_contest = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST) . "/contest/";
    unset($total_pages);
    $seen_keys = array();
    for ($page = 1; !isset($total_pages) || $page < $total_pages; $page += 1) {
        $url = $URL . "?page=$page";
        $json = curlexec($url, NULL, array("json_output" => true));
        $objects = isset($json['data'])? $json['data']['objects'] : $json;
        $ok = false;
        if (is_array($objects)) {
            foreach ($objects as $key => $data) {
                if (!isset($data["start_time"]) || !$data["start_time"]) {
                    continue;
                }
                if (isset($data['key'])) {
                    $key = $data['key'];
                }
                if (!isset($seen_keys[$key])) {
                    $seen_keys[$key] = true;
                    $ok = true;
                }
                $contests[] = array(
                    'start_time' => $data['start_time'],
                    'duration' => $data['time_limit'],
                    'end_time' => $data['end_time'],
                    'title' => $data['name'] . (isset($data['is_rated']) && $data['is_rated']? '. Rated' : ''),
                    'url' => $prefix_contest . $key,
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $key,
                );
            }
        }
        if ($ok && isset($json['data']['total_pages'])) {
            $total_pages = $json['data']['total_pages'];
        } else {
            break;
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
