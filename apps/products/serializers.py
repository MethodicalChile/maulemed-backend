from rest_framework import serializers

from apps.organizations.serializers import (
    BranchSmallSerializer,
    CostCenterSmallSerializer,
)
from apps.common.services.supabase_storage import (
    SupabaseStorageError,
    delete_file,
    get_public_url,
)
from apps.products.services.product_images import (
    ProductImageValidationError,
    upload_product_image,
)

from .models import (
    BranchProduct,
    Product,
    ProductCategory,
    UnitOfMeasure,
)


class ProductCategorySmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = [
            "uuid",
            "name",
        ]


class UnitOfMeasureSmallSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = [
            "uuid",
            "code",
            "name",
        ]


class ProductSmallSerializer(serializers.ModelSerializer):
    category_detail = ProductCategorySmallSerializer(
        source="category",
        read_only=True,
    )

    unit_detail = UnitOfMeasureSmallSerializer(
        source="unit",
        read_only=True,
    )

    image_url = serializers.SerializerMethodField(
        read_only=True,
    )

    class Meta:
        model = Product
        fields = [
            "uuid",
            "name",
            "image_url",
            "sku",
            "barcode",
            "internal_code",
            "category_detail",
            "unit_detail",
            "requires_lot",
            "requires_expiration_date",
            "is_medication",
            "is_controlled",
            "is_active",
        ]

    def get_image_url(self, product):
        if not product.image_path:
            return None

        return get_public_url(product.image_path)


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        exclude = [
            "id",
            "deleted_at",
        ]


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        exclude = [
            "id",
            "deleted_at",
        ]


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=ProductCategory.objects.all(),
    )

    unit = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=UnitOfMeasure.objects.all(),
    )

    category_detail = ProductCategorySmallSerializer(
        source="category",
        read_only=True,
    )

    unit_detail = UnitOfMeasureSmallSerializer(
        source="unit",
        read_only=True,
    )

    image = serializers.ImageField(
        write_only=True,
        required=False,
        allow_null=True,
    )

    image_url = serializers.SerializerMethodField(
        read_only=True,
    )

    remove_image = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
    )

    class Meta:
        model = Product
        exclude = [
            "id",
            "deleted_at",
        ]

        read_only_fields = [
            "image_path",
        ]

    def get_image_url(self, product):
        if not product.image_path:
            return None

        return get_public_url(product.image_path)

    def validate_image(self, image):
        if not image:
            return image

        max_size = 5 * 1024 * 1024

        if image.size > max_size:
            raise serializers.ValidationError(
                "La imagen no puede superar los 5 MB."
            )

        allowed_content_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

        content_type = getattr(
            image,
            "content_type",
            None,
        )

        if content_type not in allowed_content_types:
            raise serializers.ValidationError(
                "Solo se permiten imágenes JPG, PNG o WEBP."
            )

        return image

    def create(self, validated_data):
        image = validated_data.pop(
            "image",
            None,
        )

        validated_data.pop(
            "remove_image",
            None,
        )

        product = super().create(
            validated_data,
        )

        if not image:
            return product

        try:
            image_path = upload_product_image(
                product_uuid=product.uuid,
                image=image,
            )
        except (
            ProductImageValidationError,
            SupabaseStorageError,
        ) as exc:
            product.delete()

            raise serializers.ValidationError({
                "image": str(exc),
            }) from exc

        product.image_path = image_path

        product.save(
            update_fields=[
                "image_path",
                "updated_at",
            ]
        )

        return product

    def update(self, instance, validated_data):
        image = validated_data.pop(
            "image",
            None,
        )

        remove_image = validated_data.pop(
            "remove_image",
            False,
        )

        previous_image_path = instance.image_path

        product = super().update(
            instance,
            validated_data,
        )

        if remove_image and not image:
            product.image_path = ""

            product.save(
                update_fields=[
                    "image_path",
                    "updated_at",
                ]
            )

            if previous_image_path:
                delete_file(previous_image_path)

            return product

        if not image:
            return product

        try:
            new_image_path = upload_product_image(
                product_uuid=product.uuid,
                image=image,
            )
        except (
            ProductImageValidationError,
            SupabaseStorageError,
        ) as exc:
            raise serializers.ValidationError({
                "image": str(exc),
            }) from exc

        product.image_path = new_image_path

        product.save(
            update_fields=[
                "image_path",
                "updated_at",
            ]
        )

        if previous_image_path:
            delete_file(previous_image_path)

        return product
        
class BranchProductSerializer(serializers.ModelSerializer):
    branch_detail = BranchSmallSerializer(
        source="branch",
        read_only=True,
    )

    product_detail = ProductSmallSerializer(
        source="product",
        read_only=True,
    )

    cost_center_detail = CostCenterSmallSerializer(
        source="cost_center",
        read_only=True,
    )

    class Meta:
        model = BranchProduct
        exclude = [
            "id",
            "deleted_at",
        ]