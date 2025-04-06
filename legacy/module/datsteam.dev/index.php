<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $events_url = $URL;
    $page = curlexec($events_url);
    preg_match_all('#<div[^>]*class="support-ticket[^"]*"[^>]*data-id="(?P<id>[^"]*)"[^>]*data-url="(?P<url>[^"]*)".*?<h[^>]*class="ticket-title"[^>]*>(?P<title>[^<]*)</h.>#s', $page, $matches, PREG_SET_ORDER);

    foreach ($matches as $contest) {
        $title = trim($contest['title']);
        $url = url_merge($events_url, $contest['url']);
        $url = urldecode($url);
        $url = str_replace('&amp;', '&', $url);
        $url = preg_replace('/(pagesize|pageid)=\d+&?/', '', $url);

        $event_page = curlexec($url);
        preg_match_all('#<tr[^>]*>\s*<td>(?P<key>[^<]*)</td>\s*<td>(?P<value>.*?)</td>\s*</tr>#', $event_page, $matches, PREG_SET_ORDER);
        $info = [];
        foreach ($matches as $match) {
            $key = slugify(trim($match['key']));
            $value = strip_tags(trim($match['value']));
            $info[$key] = $value;
        }
        if (!isset($info['event-start']) || !isset($info['event-end'])) {
            continue;
        }

        $event_url = 'https://datsteam.dev/' . strtolower($title);
        $headers = get_headers($event_url);
        if (strpos($headers[0], '200') !== false) {
            $url = $event_url;
        }

        $contests[] = array(
            'start_time' => $info['event-start'],
            'end_time' => $info['event-end'],
            'title' => $title,
            'url' => $url,
            'key' => $contest['id'],
            'info' => ['parse' => $info],
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
        );
    }
?>
