<?php
  require_once dirname(__FILE__) . '/../../config.php';

  foreach (['Active', 'Archived'] as $activity) {
    $skip = 0;
    $count = 100;

    for (;;) {
      $url = "https://api.algoleague.com/api/app/contests?Content=Contest&ContestActivity=$activity&SkipCount=$skip&MaxResultCount=$count&CombineWith=And";
      $data = curlexec($url, null, ["json_output" => true]);
      if (!isset($data["totalCount"]) || $data["totalCount"] <= $skip) {
        break;
      }
      foreach ($data["items"] as $c) {
        if (!isset($c['endDate'])) {
          continue;
        }
        $title = $c['name'];
        $tags = array();
        foreach (['contestScoring', 'contestType', 'participationType'] as $field) {
          if (isset($c[$field]) && !empty($c[$field])) {
            $tags[] = slugify($c[$field]);
          }
        }
        if (!empty($tags)) {
          $title .= ' (' . implode(', ', $tags) . ')';
        }
        $contests[] = array(
          'title' => $title,
          'start_time' => $c['startDate'],
          'end_time' => $c['endDate'],
          'duration' => $c['length'],
          'url' => url_merge($URL, "/contest/{$c['slug']}/"),
          'host' => $HOST,
          'rid' => $RID,
          'timezone' => $TIMEZONE,
          'key' => $c['id'],
          'info' => ['parse' => $c],
        );
      }
      if (!isset($_GET['parse_full_list'])) {
        break;
      }
      $skip += $count;
    }
  }
?>
