function filterCallbackList(regex) {
    if (regex) {
        try {
            regex = new RegExp(regex, 'i')
        } catch (e) {
            regex = null;
        }
    }

    if (regex) {
        $('.contest .toggle, #toggle-all').each(function() {
            $(this).addClass('hidden')
        })
        var count = 0
        $('.contest').each(function() {
            var title = $(this).find('.event a[title]:first').attr('title')
            var host = $(this).find('.resource a:first').text()
            if (regex.test(title) || regex.test(host)) {
                $(this).addClass('onfilter').removeClass('nofilter')
                count += 1
            } else {
                $(this).addClass('nofilter').removeClass('onfilter')
            }
        })
        $('#filter-count-matches').removeClass('hidden').html(count)
    } else {
        $('.contest .toggle, #toggle-all').each(function() {
            $(this).removeClass('hidden')
        })
        $('.contest').each(function() {
            $(this).removeClass('nofilter').removeClass('onfilter')
        })
        $('#filter-count-matches').addClass('hidden')
    }
}
