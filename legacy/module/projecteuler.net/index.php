<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://projecteuler.net/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/London';
    if (!isset($contests)) $contests = array();

    $urls = array('https://projecteuler.net/recent');

    if (isset($_GET['parse_full_list'])) {
        $url = 'https://projecteuler.net/archives';
        $page = curlexec($url);
        preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[0-9]+</a>#', $page, $matches);
        foreach ($matches['url'] as $u) {
            $urls[] = url_merge($url, $u);
        }
        $urls = array_unique($urls);
    }

    foreach ($urls as $url) {
        $page = curlexec($url);
        preg_match_all('#
            <tr>\s*
                <td[^>]*>(?P<key>[0-9]+)</td>\s*
                <td[^>]*>
                    <a[^>]*href="(?P<url>[^"]*)"[^>]*Published\s*on\s*(?P<start_time>[^"]*)"[^>]*>
                        (?P<name>.*?)
                    </a>\s*</td>#x',
            $page,
            $matches,
            PREG_SET_ORDER
        );

        foreach ($matches as $match) {
            $contests[] = array(
                'start_time' => $match['start_time'],
                'duration' => '00:00',
                'title' => "Problem ${match['key']}. ${match['name']}",
                'url' => url_merge($url, $match['url']),
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'key' => $match['key']
            );
        }
    }
    if ($RID == -1) {
        print_r($contests);
    }
?>
