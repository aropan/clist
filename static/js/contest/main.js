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
            var title = $(this).find('.event .title_search').attr('title')
            var host = $(this).find('.event .resource_search').text()
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


$(function() {
    $('#send_notification').on('show.bs.modal', function (event) {
        var button = $(event.relatedTarget)
        var title = button.data('title')
        var contest_id = button.data('contest-id')
        var method = button.data('method')

        var modal = $(this)
        modal.find('.modal-title').text(title)
        modal.find('[name="contest_id"]').val(contest_id)
        modal.find('select option[value="' + method + '"]').attr('selected', 'true')
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
        }).fail(function() {
            $('#send_notification').effect("shake")
        });
        e.preventDefault();
    });
})
