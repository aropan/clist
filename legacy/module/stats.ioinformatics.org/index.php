<?php

global $contests, $HOST, $TIMEZONE, $RID, $PARSE_FULL_LIST;

require_once dirname(__FILE__) . '/../../config.php';

$page = curlexec($URL);

preg_match_all(
    '#
    <tr>\s*
    <td[^>]*>\s*<a[^>]*>\s*(?P<key>(?P<no>[0-9]+))\s*</a>\s*</td>
    <td[^>]*>\s*<a[^>]*href="(?P<url>[^>]*)"[^>]*>\s*[0-9]{2,4}\s*</a>\s*</td>
    <td[^>]*>(?P<start_time>[^<]*)\s*&ndash;\s*(?P<end_time>[^<]*)</td>
    <td[^>]*>\s*<a[^>]*>(?P<country>[^<]*)</a>\s*</td>
    #x',
    $page,
    $matches,
    PREG_SET_ORDER,
);

$website_attempted = false;
foreach ($matches as $match) {
    $no = $match['no'];
    $contest = [
        'start_time' => trim($match['start_time']),
        'end_time' => trim($match['end_time']),
        'title' => $no . ending_ordinal($no) . ' International Olympiad in Informatics. ' . trim($match['country']),
        'url' => url_merge($URL, '/' . ltrim($match['url'], '/')),
        'key' => $match['key'],
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'rid' => $RID,
        'unchanged' => ['duration_in_secs'],
    ];

    if (!$website_attempted || $PARSE_FULL_LIST) {
        $url = $contest['url'];
        $page = curlexec($url);
        if (preg_match('#<a[^>]*href="(?P<href>[^"]*)"[^>]*>Official website</#', $page, $website_match)) {
            $website = $website_match['href'];
            $website = preg_replace('#\bwww\.#', '', $website);
            $contest['info'] = ['parse' => ['website' => $website]];
        }
        $website_attempted = true;
    }
    $contests[] = $contest;
}
