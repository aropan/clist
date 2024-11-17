function filterCallbackList() {
    var regex = $('#filter #search').val()
    update_urls_params({'q': regex? regex : undefined})
    if (regex) {
        try {
            regex = new RegExp(regex, 'i')
        } catch (e) {
            regex = null;
        }
    }

    var favorite_value = $('#filter button[name="favorite"].active').data('value')
    if (favorite_value == 'on') {
        favorite_value = 'true'
        update_urls_params({'favorite': 'on'})
    } else if (favorite_value == 'off') {
        favorite_value = 'false'
        update_urls_params({'favorite': 'off'})
    } else {
        update_urls_params({'favorite': undefined})
    }

    if (regex || favorite_value) {
        $('.contest .toggle, #toggle-all').each(function() {
            $(this).addClass('hidden')
        })
        var count = 0
        $('.contest').each(function() {
            var title = $(this).find('.event .title-search').attr('title')
            var host = $(this).find('.event .resource-search').text()
            var fav = Boolean($(this).find('.fav.selected-activity').length)
            var regexed = regex? regex.test(title) || regex.test(host) : true
            var favorited = favorite_value? String(fav) == favorite_value : true
            if (regexed && favorited) {
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


$(function() {
    $('#send_notification').on('show.bs.modal', function (event) {
        var button = $(event.relatedTarget)
        var title = button.data('title')
        var contest_id = button.data('contest-id')
        var method = button.data('method')

        var modal = $(this)
        modal.find('.modal-title').text(title)
        modal.find('[name="contest_id"]').val(contest_id)
        modal.find('select option[value="' + method + '"]').attr('selected', 'true').trigger('change')
    })

    $('#send_notification form').submit(function(e) {
        var form = this;
        var $form = $(this);
        $.ajax({
            type: $form.attr('method'),
            url: $form.attr('action'),
            data: $form.serialize()
        }).done(function() {
            form.reset();
            $('#send_notification').modal('hide')
        }).fail(function(response) {
            log_ajax_error(response)
            $('#send_notification').effect("shake")
        });
        e.preventDefault();
    });

    $('#skip-promotion').click(function() {
        $.ajax({
            type: 'POST',
            url: skip_promotion_url,
            data: {'id': $(this).data('promotion-id')},
            success: function() { $('#promotion').hide() },
            error: log_ajax_error_callback,
        })
    })
})
