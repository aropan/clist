<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $cids = array();
    for ($n_page = 1;; $n_page += 1) {
        $contest_list_url = $URL . '?page=' . $n_page;
        $page = curlexec($contest_list_url);

        if (!preg_match_all('#<tr[^>]*>\s*<td[^>]*>(?P<cid>[0-9]+)</td>\s*<td[^>]*>\s*<a\s*href="(?P<url>[^"]*)">(?<title>[^<]*)</a>\s*</td>\s*<td[^>]*>[^<]*</td>(?:\s*<[^>]*>)*(?P<type>[^<]*)#', $page, $matches, PREG_SET_ORDER)) {
            break;
        }

        $ok = false;
        foreach ($matches as $c) {
            $url = url_merge($URL, $c['url']);

            $key = $c['cid'];
            if (isset($cids[$key])) {
                continue;
            }
            $cids[$key] = true;
            $ok = true;

            $page = curlexec($url);

            if (!preg_match('#<[^>]*class="fa fa-clock-o"[^>]*>(?:\s*</[^>]*>)*(?:\s*<[^/][^>]>)?\s*(?P<time>(?:[0-9]+[- :]+){11}[0-9]+)\s*<#', $page, $match)) {
                echo $url . "\n";
                continue;
            }
            preg_match_all('#(?:[0-9]+[- :]+){5}[0-9]+#', $match['time'], $time);
            list($start_time, $end_time) = $time[0];


            $title = $c['title'];
            if (isset($c['type']) && $c['type'] && $c['type'] != 'Register Public') {
                $title .= '. ' . $c['type'];
            }

            $contests[] = array(
                'start_time' => $start_time,
                'end_time' => $end_time,
                'title' => $title,
                'url' => url_merge($URL, $c['url']),
                'key' => $key,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
            );
        }

        if (!$ok || !isset($_GET['parse_full_list'])) {
            break;
        }
    }
?>
