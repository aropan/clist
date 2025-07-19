<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $urls = array($URL, 'https://contest.yandex.ru/CYF/archive/');
    $parse_full_list = isset($_GET['parse_full_list']);

    $seen_urls = array();
    foreach ($urls as $url) {
        $seen_urls[$url] = true;
    }

    function upsolving_priority_sort($a, $b) {
        $result = isset($b['upsolving_key']) <=> isset($a['upsolving_key']);
        if ($result == 0) {
            $result = intval($a['key']) <=> intval($b['key']);
        }
        return $result;
    }

    $raw_contests = array();
    while ($urls) {
        $url = array_shift($urls);
        $page = curlexec($url);

        if ($parse_full_list) {
            preg_match_all('#<a[^>]*href="(?P<url>[^"]*contest.yandex.ru/(?:CYF/)?archive[^/][^?"]*)"[^>]*>(?P<desc>.*?)</a>#i', $page, $matches, PREG_SET_ORDER);
            foreach ($matches as $match) {
                $url = $match['url'];
                if (isset($seen_urls[$url])) {
                    continue;
                }
                $seen_urls[$url] = true;
                $urls[] = $url;
            }
        }

        preg_match_all(
            '#
            <a[^>]*href="(?P<url>[^"]*contest.yandex.ru/(?:CYF/)?contest/(?P<key>[0-9]+)[^"]*)"[^>]*>(?P<desc>.*?)</a>
            (?:
            .*<a[^>]*href="(?P<upsolving_url>[^"]*contest.yandex.ru/(?:CYF/)?contest/(?P<upsolving_key>[0-9]+)[^"]*)"[^>]*>[^/]*>(?P<upsolving_desc>[^>]*[дД]орешивание[^<]*)
            )?
            #ix',
            $page,
            $matches,
            PREG_SET_ORDER,
        );
        usort($matches, 'upsolving_priority_sort');
        $limit = 10;
        $max_ids = array();
        foreach ($matches as $match) {
            if (!$parse_full_list) {
                $id = intval($match['key']);
                if (count($max_ids) >= $limit && $id < end($max_ids)) {
                    continue;
                }
                $max_ids[] = $id;
                rsort($max_ids);
                $max_ids = array_slice($max_ids, 0, $limit);
            }
            $raw_contests[] = $match;
        }
    }

    usort($raw_contests, 'upsolving_priority_sort');
    $ids = array();
    foreach ($raw_contests as $raw_contest) {
        if (isset($ids[$raw_contest['key']])) {
            continue;
        }
        $ids[$raw_contest['key']] = true;

        $page = curlexec($raw_contest['url']);
        preg_match_all('#<div[^>]*class="status__prop"[^>]*>[^<]*<[^>]*>(?P<name>[^<]+)</[^>]*>[^<]*<[^>]*>(?<value>[^<]*)<(?:time[^>]*timestamp[^:]*:(?P<ts>[0-9]+))?#', $page, $ms, PREG_SET_ORDER);
        $values = array();
        foreach ($ms as $m) {
            $values[$m['name']] = $m;
        }

        if (!preg_match('#<div[^>]*class="[^"]*title">[^<]*(<[^/>]*>[^<]*)*<a[^>]*contest/[0-9]+[^>]*>(?P<title>[^<]*)</a>#', $page, $m)) {
            continue;
        }
        $title = html_entity_decode($m['title']);

        $contest = array_merge(
            $INFO['update']['default_fields'],
            array(
                'title' => $title,
                'url' => $raw_contest['url'],
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $raw_contest['key'],
                'upsolving_key' => get_item($raw_contest, ['upsolving_key']),
                'upsolving_url' => get_item($raw_contest, ['upsolving_url']),
            )
        );
        $contest['has_unlimited_statistics'] = empty($contest['upsolving_key'])? 'false' : 'true';

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

    if ($RID == -1) {
        print_r($contests);
    }
?>
