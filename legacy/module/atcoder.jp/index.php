<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://atcoder.jp/contests/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'JST';
    if (!isset($contests)) $contests = array();

    $seen = array();
    foreach (array('?lang=en' => '', '?lang=ja' => '?lang=ja') as $query => $host) {
        $url = $URL . $query;

        $url_parsed = array();
        do {
            $page = curlexec($url);
            $url_parsed[$url] = true;

            $regex = '#
                <tr[^>]*>(?:\s*<[^>]*>)+(?P<start_time>[^<]*)(?:<[^>]*>\s*)+
                (?:<span[^>]*class="(?P<class>[^"]*)"[^>]*>[^<]*</span>\s*)?
                <a[^>]*href=[\"\'](?P<url>[^\"\']*/(?P<key>[^/]*))[\"\'][^>]*>(?P<title>[^<]*)(?:<[^>]*>\s*)+
                (?P<duration>[0-9]+(?::[0-9]+)+)
                </td>
            #x';

            preg_match_all($regex, $page, $matches, PREG_SET_ORDER);

            foreach ($matches as $c) {
                $k = $c['key'];
                if (isset($seen[$k])) {
                    continue;
                }
                $seen[$k] = true;

                $title = $c['title'];
                if (!empty($c['class'])) {
                    $classes = explode(' ', $c['class']);
                    foreach (
                        array(
                            array('class' => 'user-red', 'prefix' => 'AGC', 'name' => 'AtCoder Grand Contest'),
                            array('class' => 'user-orange', 'prefix' => 'ARC', 'name' => 'AtCoder Regular Contest'),
                            array('class' => 'user-blue', 'prefix' => 'ABC', 'name' => 'AtCoder Beginner Contest'),
                            array('class' => 'user-green', 'prefix' => 'ABC', 'name' => 'AtCoder Beginner Contest'),
                        ) as $t
                    ) {
                        if (in_array($t['class'], $classes) && stripos($title, $t['name']) === false) {
                            $title = $t['prefix'] . ": " . $title;
                            break;
                        }
                    }
                }

                $contests[] = array(
                    'start_time' => $c['start_time'],
                    'duration' => $c['duration'],
                    'title' => $title,
                    'url' => url_merge($URL, $c['url']),
                    'host' => $HOST . $host,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                    'key' => $k
                );
            }

            $url = false;
            preg_match_all("#<a[^>]*href=[\"'](?P<url>[^\"']*/contests/archive(?:\?page=[0-9]+)?)[^>]*>#", $page, $matches);
            foreach ($matches['url'] as $u) {
                $u = url_merge($URL, $u);
                if (!isset($url_parsed[$u])) {
                    $url = $u;
                    break;
                }
            }
        } while (isset($_GET['parse_full_list']) && $url);
    }

    if ($RID === -1) {
        print_r($contests);
    }
?>
