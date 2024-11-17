<?php
    require_once dirname(__FILE__) . '/../../config.php';

    $_contests = $contests;
    $contests = array();

    $subdomains = $INFO['update']['subdomains'];
    foreach ($subdomains as $subdomain_format) {
        $n_skip = 0;
        for ($year = current_season_year() + 1, $iter = 0; $n_skip < 3; $year--, $iter++) {
            $subdomain = strtr($subdomain_format, array('{YY}' => substr($year, 2, 2), '{YYYY}' => $year));
            $HOST = "$subdomain.kattis.com";
            $URL = "https://$HOST/contests/";
            $n_contests = -count($contests);
            include './module/open.kattis.com/index.php';
            $n_contests += count($contests);
            $n_skip = $n_contests ? 0 : $n_skip + 1;
            if ($iter >= 2 && !isset($_GET['parse_full_list'])) {
                break;
            }
        }
    }

    foreach ($contests as $contest) {
        if (preg_match('/\b(practice|warmup|test|hidden)\b/i', $contest['title'])) {
            continue;
        }
        $_contests[] = $contest;
    }
    $contests = $_contests;
?>
