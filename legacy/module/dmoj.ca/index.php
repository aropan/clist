<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $prefix_contest = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST) . "/contest/";
    unset($total_pages);
    for ($page = 1; !isset($total_pages) || $page < $total_pages; $page += 1) {
        $url = $URL . "?page=$page";
        $json = curlexec($url, NULL, array("json_output" => true));
        if ($json && is_array($json['data']['objects'])) {
            foreach ($json['data']['objects'] as $data) {
                if (!isset($data["start_time"]) || !$data["start_time"]) {
                    continue;
                }
                $contests[] = array(
                    'start_time' => $data['start_time'],
                    'duration' => $data['time_limit'],
                    'end_time' => $data['end_time'],
                    'title' => $data['name'] . ($data['is_rated']? '. Rated' : ''),
                    'url' => $prefix_contest . $data['key'],
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $data['key'],
                );
            }
        }
        if (isset($json['data']['total_pages'])) {
            $total_pages = $json['data']['total_pages'];
        } else {
            break;
        }
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
