<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $debug_ = $RID == -1 || DEBUG;

    $parse_full_list = isset($_GET['parse_full_list']);

    $year = date('Y');
    for (;; --$year) {
        $url = "https://contest.yandex.com/algorithm${year}";
        if ($debug_) {
            echo $url . "\n";
        }

        $page = curlexec($url);

        $urls = array();

        preg_match_all('#<a[^>]*href="(?P<href>[^"]*/algorithm' . $year .'/[^>]+)">#', $page, $matches);
        foreach ($matches['href'] as $href) {
            $u = url_merge($url, $href);
            if (preg_match('#/contest/[0-9]+/#', $u)) {
                $urls[] = $u;
                continue;
            }
            $p = curlexec($u);
            preg_match_all('#<a[^>]*href="(?P<href>[^"]*/contest/[0-9]+/[^>]*)">#', $p, $ms);
            foreach ($ms['href'] as $h) {
                $urls[] = url_merge($u, $h);
            }
        }

        $contest_urls = array();
        foreach ($urls as $u) {
            $u = preg_replace('#yandex.ru#', "yandex.com", $u);
            $u = preg_replace('#.com/contest#', ".com/algorithm${year}/contest", $u);
            $u = preg_replace('#(/contest/[0-9]+).*$#', '\1/', $u);
            $contest_urls[] = $u;
        }
        $contest_urls = array_unique($contest_urls);

        $ids = array();
        foreach ($contest_urls as $url) {
            if (!preg_match('#/contest/(?P<key>[0-9]+)/#', $url, $match)) {
                continue;
            }
            $key = $match['key'];

            if (isset($ids[$key])) {
                continue;
            }
            $ids[$key] = true;

            $page = curlexec($url);
            preg_match_all('#<div[^>]*class="status__prop"[^>]*>[^<]*<div[^>]*>(?P<name>[^<]+)</div>[^<]*<div[^>]*>(?<value>[^<]*)<(?:time[^>]*timestamp[^:]*:(?P<ts>[0-9]+))?#', $page, $ms, PREG_SET_ORDER);
            $values = array();
            foreach ($ms as $m) {
                $values[$m['name']] = $m;
            }

            if (!preg_match('#<div[^>]*class="[^"]*title">[^<]*<a[^>]*contest/[0-9]+[^>]*>(?P<title>[^<]*)</a>#', $page, $m)) {
                continue;
            }
            $title = html_entity_decode($m['title']);

            $contest = array(
                'title' => $title,
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $key,
            );

            foreach (
                array(
                    'начало:' => 'start_time',
                    'start:' => 'start_time',
                    'конец:' => 'end_time',
                    'end:' => 'end_time',
                    'длительность:' => 'duration',
                    'duration:' => 'duration',
                ) as $k => $v
            ) {
                if (!empty($values[$k]['value'])) {
                    $contest[$v] = html_entity_decode($values[$k]['value']);
                } else if (!empty($values[$k]['ts'])) {
                    $contest[$v] = $values[$k]['ts'] / 1000;
                }
            }
            if (!empty($contest['duration']) && substr_count($contest['duration'], ':') >= 2) {
                $a = explode(':', $contest['duration']);
                $contest['duration'] = implode(':', array_slice($a, 0, 2));
            }

            $contests[] = $contest;
        }

        if (!$parse_full_list) {
            break;
        }

        if (count($contests) && !count($contest_urls)) {
            break;
        }
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
