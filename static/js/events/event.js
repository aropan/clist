$(function() {
    var $organization = $('#organization')
    $organization.select2({
        width: '100%',

        tags: true,
        createTag: function (params) {
            if (params.term) {
                return { id: params.term, text: params.term, newOption: true }
            }
        },

        ajax: {
            url: search_url,
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return { query: 'organization', name: params.term, page: params.page || 1 }
            },
            processResults: function (data, params) {
                return { results: data.items, pagination: { more: data.more } }
            },
        },
        minimumInputLength: 0
    })

    var $team = $('#team')
    $team.select2({
        width: '100%',

        tags: true,
        createTag: function (params) {
            if (params.term) {
                return { id: params.term, text: params.term, newOption: true }
            }
        },

        templateResult: function (data) {
            var $result = $('<span></span>')
            $result.text(data.text)
            if (data.newOption) {
                $result.append(' <em>(create a new team)</em>')
            }
            return $result
        },

        ajax: {
            url: search_url,
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return { query: 'team', name: params.term, page: params.page || 1 }
            },
            processResults: function (data, params) {
                return { results: data.items, pagination: { more: data.more } }
            },
        },
        minimumInputLength: 0,
        maximumInputLength: team_name_limit,
    })
    $team.on('select2:close', function (e) {
        data = $team.select2('data')[0]
        if (data == undefined) {
            $('#join-team').show()
            $('#create-team').show()
        } else {
            if (data.newOption) {
                $('#join-team').hide()
                $('#create-team').show()
            } else {
                $('#join-team').show()
                $('#create-team').hide()
            }
            $('#create-team').prop('disabled', false)
            $('#join-team').prop('disabled', false)
        }
    })

    $('#email').select2({
        width: '100%',
        minimumResultsForSearch: -1
    })

    var $country = $('#country')
    $country.select2({
        width: '100%',
        templateResult: function (data) {
            var $result = $('<span></span>')

            $result.text(data.text)
            if (data.id) {
                var code = data.id.toLowerCase()
                $result.prepend('<img class="flag flag-' + code + '"/>&nbsp;')
            }
            return $result
        },

        ajax: {
            url: search_url,
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return { query: 'country', name: params.term, page: params.page || 1 }
            },
            processResults: function (data, params) {
                return { results: data.items, pagination: { more: data.more } }
            },
        },
        minimumInputLength: 0
    })

    $('#tshirt-size').select2({
        width: '100%',
        minimumResultsForSearch: -1,
    })

    $('#enable-register').on('click', function(event) {
        event.preventDefault()
        $('button[value="register"][name="query"]').removeAttr('disabled')
        $('#enable-register').parent().hide()
    });

    $('.button-status').on('click', function(event) {
        if ($('.button-status.active').length == 0) {
            $('.team.list-group-item').toggle()
        }
        $('.' + $(this).attr('value')).toggle()
        $(this).toggleClass('active')
        if ($('.button-status.active').length == 0) {
            $('.team.list-group-item').toggle()
        }
    });
})
