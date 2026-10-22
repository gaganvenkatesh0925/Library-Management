from rest_framework import serializers

from .models import Book, Borrower, loan_rule_errors


class BorrowerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Borrower
        fields = ["id", "borrower_id", "name"]


class BookSerializer(serializers.ModelSerializer):
    # Clients send/receive the borrower's card ID ("B001") instead of an internal
    # database number. Only existing borrowers are accepted.
    borrower = serializers.SlugRelatedField(
        slug_field="borrower_id",
        queryset=Borrower.objects.all(),
        allow_null=True,
        required=False,
        error_messages={"does_not_exist": "Borrower '{value}' does not exist."},
    )
    borrower_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Book
        fields = [
            "id", "status", "status_display", "title", "number_of_copies", "author",
            "date_of_borrow", "return_due_date", "borrower", "borrower_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_borrower_name(self, book):
        return book.borrower.name if book.borrower else None

    def validate(self, attrs):
        # For PATCH, fields not sent keep their current values, so combine them.
        def current(field):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, None) if self.instance else None

        status = current("status") or Book.Status.AVAILABLE

        # An Available book is on the shelf: clear any old loan details.
        if status == Book.Status.AVAILABLE:
            attrs["borrower"] = None
            attrs["date_of_borrow"] = None
            attrs["return_due_date"] = None
            return attrs

        errors = loan_rule_errors(
            status, current("borrower"), current("date_of_borrow"), current("return_due_date")
        )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
