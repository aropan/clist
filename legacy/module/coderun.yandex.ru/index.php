<?php
  require_once dirname(__FILE__) . "/../../config.php";
  $url = $URL;
  $data = curlexec($url);
  $seasons = array();
  if (preg_match('/"primarySeason":({[^}]+})/', $data, $primary_season)) {
    $primary_season = json_decode($primary_season[1], true);
    $seasons[] = $primary_season;
    $url = '/seasons/' . $primary_season['slug'];
    $data = curlexec($url);

    if (preg_match('/"pastSeasons":(\[(\{[^]]+\},?)*\])/', $data, $past_seasons)) {
      $past_seasons = json_decode($past_seasons[1], true);
      $seasons = array_merge($seasons, $past_seasons);
    }
  }

  foreach ($seasons as $season) {
    $slug = $season['slug'];
    $url = "/api/seasons/$slug/season-info";
    $data = curlexec($url, null, ['json_output' => true]);
    if (isset($data['error'])) {
      trigger_error("Warning error on $slug season: {$data['error']}", E_USER_WARNING);
      continue;
    }
    $data = get_item($data, ['result']);
    $tracks = pop_item($data, ['tracks']);
    $skip_stage = false;
    foreach ($tracks as $track) {
      $data['slug'] = $slug;
      $data['track'] = $track;

      $url = url_merge($HOST_URL, "/seasons/$slug/tracks/{$track['slug']}/");
      $start_time = $data['startDate'];
      $end_time = $data['endDate'];

      if (count($tracks) == 1 && $data['title'] == $track['title']) {
        $skip_stage = true;
        $title = $data['title'];
        $key = $slug;
      } else {
        $title = $data['title'] . '. ' . $track['title'];
        $key = $slug . '/' . $track['slug'];
      }

      $contests[] = array(
        'start_time' => $start_time,
        'end_time' => $end_time,
        'title' => $title,
        'url' => $url,
        'rid' => $RID,
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'key' => $key,
        'info' => ['parse' => $data],
      );
    }

    if (empty($tracks) || $skip_stage) {
      continue;
    }

    $contests[] = array(
      'start_time' => $start_time,
      'end_time' => $end_time,
      'title' => $season['title'],
      'url' => url_merge($HOST_URL, "/seasons/$slug/"),
      'rid' => $RID,
      'host' => $HOST,
      'timezone' => $TIMEZONE,
      'key' => $slug,
      'info' => array('_inherit_stage' => true),
    );
  }
?>
