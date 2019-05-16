<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://www.e-olimp.com/competitions";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Kiev';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    preg_match_all('#<li>\s*<a[^>]*href="(?<url>[^"]+)"[^>]*>\d+</a>\s*</li>#', $page, $urls);

    $urls = $urls["url"] or array();

    if (!in_array($URL, $urls)) {
        $urls[] = $URL;
    }

    $timezone_offset = timezone_offset_get(new DateTimeZone($TIMEZONE), new DateTime("now"));
    foreach ($urls as $url)
    {
        $page = curlexec($url);
        preg_match_all('#
            <td[^>]*>\s*
                <a[^>]*href="(?<url>[^"]+)">
                    (?<title>[^<]+)
                </a>\s*
                <div[^<]*>(?:<small[^>]*>[^<]*</small>)?[^<]*</div>\s*
            </td>\s*
            <td[^>]*>\s*
            (?:
                (?<start_time>[^<]+)(?:</?br/?>)+(?<end_time>[^<]+)|
                <b>(?<date>[^<]+)</b>(?:</?br/?>)+(?<date_start_time>[^\-]+)-(?<date_end_time>[^<]+)
            )
            #xs',
            $page,
            $matches
        );

        foreach ($matches[0] as $i => $value)
        {
            $matches['date'][$i] = trim($matches['date'][$i]);

            if ($matches['date'][$i] == "Сегодня") $matches['date'][$i] = date("Y-m-d", time() + $timezone_offset);
            if ($matches['date'][$i] == "Завтра") $matches['date'][$i] = date("Y-m-d", time() + 24 * 60 * 60 + $timezone_offset);

            $url = parse_url($URL, PHP_URL_SCHEME) . '://' . $HOST . '/' . trim(trim($matches['url'][$i]), '/');
            $url = preg_replace('#/(ru|en)/#', '/', $url);

            if (!preg_match("/[0-9]+$/", $url, $match)) {
                continue;
            }
            $key = $match[0];

            $contests[] = array(
                'start_time' => $matches['date'][$i]? $matches['date'][$i] . ' ' . trim($matches['date_start_time'][$i]) : trim($matches['start_time'][$i]),
                'end_time' => $matches['date'][$i]? $matches['date'][$i] . ' ' . trim($matches['date_end_time'][$i]) : trim($matches['end_time'][$i]),
                'title' => trim($matches['title'][$i]),
                'url' => $url,
                'rid' => $RID,
                'host' => $HOST,
                'timezone' => $TIMEZONE,
                'key' => $key
            );

            $i = count($contests) - 1;
            $contests[$i]['start_time'] = preg_replace("#\.(\d\d)\s#", '.' . (int)(date('Y', time()) / 100) . '\1 ', $contests[$i]['start_time']);
            $contests[$i]['end_time'] = preg_replace("#\.(\d\d)\s#", '.' . (int)(date('Y', time()) / 100) . '\1 ', $contests[$i]['end_time']);
        }
    }
?>
