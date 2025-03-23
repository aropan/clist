<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $contests_url = $URL;
    curl_setopt($CID, CURLOPT_COOKIE, "uoj_locale=en");
    $contests_page = curlexec($contests_url);
    curl_setopt($CID, CURLOPT_COOKIE, null);

    preg_match_all('#
<td[^>]*>\s*<a[^>]*href="(?P<url>[^"]*/contest/(?P<key>[0-9]+)/?)"[^>]*>(?P<title>[^<]*)(?:<b>.*?</b>)?</a>.*?</td>\s*
<td>\s*<a[^>]*>(?P<start_time>[^<]*)</a>\s*</td>\s*
<td>(?P<duration>[^<]*)</td>\s*
        #x',
        $contests_page,
        $matches,
        PREG_SET_ORDER,
    );

    foreach ($matches as $c) {
        $url = url_merge($contests_url, $c['url']);
        $contests[] = array(
            'start_time' => $c['start_time'],
            'title' => $c['title'],
            'duration' => $c['duration'],
            'url' => $url,
            'key' => $c['key'],
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
