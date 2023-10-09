<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $url = 'https://pythoncode.club/contests/rss';
    $rss = curlexec($url, NULL, array('no_header' => true));
    $xml = new SimpleXMLElement($rss);
    foreach ($xml->channel->item as $item) {
        preg_match_all('#>(?P<key>[^:<]*):(?P<value>[^<\(]*)#', $item->description, $matches);
        $keys = array_map(function($time) { return str_replace(' ', '_', strtolower($time)); }, $matches['key']);
        $values = array_map('trim', $matches['value']);
        $data = array_combine($keys, $values);

        preg_match('#/(?P<key>[^/]+)/?$#', $item->link, $match);
        $key = $match['key'];

        $contests[] = array(
            'start_time' => $data['start_time'],
            'duration' => $data['duration'],
            'title' => 'Single Problem Contest. ' . ucwords($data['difficulty']),
            'url' => $item->link,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $key,
        );
    }
?>
