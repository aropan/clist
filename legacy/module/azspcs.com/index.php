<?php
  require_once dirname(__FILE__) . "/../../config.php";

  if (!isset($_GET['parse_full_list'])) {
    return;
  }

  $main_url = "http://recmath.com/contest/archives.php";
  $page = curlexec($main_url);
  preg_match_all('#<tr><td><a\s*href="(?P<url>(?P<key>[^/]*)/index.php)">(?P<title>[^<]*)</a>#', $page, $matches, PREG_SET_ORDER);

  foreach ($matches as $match) {
    $url = url_merge($main_url, $match['url']);
    $page = curlexec($url);
    $key = $match['key'];
    $title = $match['title'];
    $title = preg_replace('#\s*contest\s*$#i', '', $title);
    $title = preg_replace("#\s*Al\s*Zimmermann's\s*#i", '', $title);

    unset($start_time, $end_time);

    if (preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[^<]*description[^<]*</a>#i', $page, $match)) {
      $description_url = url_merge($url, $match['url']);
      $description_page = curlexec($description_url, NULL, ['no_convert_charset' => true, 'no_header' => true]);
    } else {
      $description_page = $page;
    }

    $start_regex = '#(?:start|begin)\w*:(?:\s*|<[^>]*>|&nbsp;)*(?P<start_time>[^<]+[^;])<#i';
    if (preg_match($start_regex, $page, $match) || preg_match($start_regex, $description_page, $match)) {
      $start_time = preg_replace('#\s*,\s*#', ' ', $match['start_time']);
      $start_time = strtotime($start_time);
    }
    $end_regex = '#(?:end)\w*:(?:\s*|<[^>]*>|&nbsp;)*(?P<end_time>[^<]+[^;])<#i';
    if (preg_match($end_regex, $page, $match) || preg_match($end_regex, $description_page, $match)) {
      $end_time = preg_replace('#\s*,\s*#', ' ', $match['end_time']);
      $end_time = strtotime($end_time);
    }


    if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[^<]*standings[^<]*</a>#i', $page, $match)) {
      preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>[^<]*final\s*results[^<]*</a>#i', $page, $match);
    }
    $standings_url = url_merge($url, $match['url']);

    if (!isset($start_time) && !isset($end_time)) {
      $standings_page = curlexec($standings_url, NULL, ['no_convert_charset' => true, 'no_header' => true]);
      $date_regex = '#(?:\d+-\d+-\d+ \d+:\d+:\d+|\d+ \w+ \d+\s*(?:<[^>]*>|,\s*)?\d+:\d+:\d+|\w+ \d+, \d{4})#i';
      preg_match_all($date_regex, $standings_page, $matches1, PREG_SET_ORDER);
      preg_match_all($date_regex, $description_page, $matches2, PREG_SET_ORDER);
      $matches = array_merge($matches1, $matches2);

      foreach ($matches as $match) {
        $time = $match[0];
        $time = preg_replace('#<[^>]*>#', ' ', $time);
        $time = preg_replace('#\s*,\s*#', ' ', $time);
        $time = strtotime($time);
        if (!$time) {
          continue;
        }
        if (!isset($start_time) || $time < $start_time) {
          $start_time = $time;
        }
        if (!isset($end_time) || $time > $end_time) {
          $end_time = $time;
        }
      }
    } else if (!isset($start_time)) {
      $start_time = $end_time;
    } else if (!isset($end_time)) {
      $end_time = $start_time;
    }

    $contests[] = array(
      "start_time" => $start_time,
      "end_time" => $end_time,
      "title" => $title,
      "url" => $url,
      "key" => $key,
      "rid" => $RID,
      "host" => $HOST,
      "standings_url" => $standings_url,
    );
  }
  // print_r($matches);
?>
