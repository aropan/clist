<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($HOST)) $URL = "http://acm.bsuir.by/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($TIMEZONE)) $INFO = array();
    if (!isset($contests)) $contests = array();


    for ($year = date('Y'); ; --$year) {
        $url = "http://contest.yandex.ru/bsuir{$year}";

        $page = curlexec($url);

        if (!preg_match_all('#<a[^>]*href="(?P<url>[^"]*/contest/(?P<key>[0-9]+)[^"]*)#i', $page, $matches, PREG_SET_ORDER)) {
            break;
        }

        $ids = array();
        foreach ($matches as $match) {
            if (isset($ids[$match['key']])) {
                continue;
            }
            $ids[$match['key']] = true;
            $page = curlexec($match['url']);
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
                'url' => $match['url'],
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $match['key'],
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
        if (!isset($_GET['parse_full_list'])) {
            break;
        }
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
