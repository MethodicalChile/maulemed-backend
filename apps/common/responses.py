from rest_framework import status
from rest_framework.response import Response


def api_response(
    data=None,
    status_code=status.HTTP_200_OK,
    message="Operación realizada correctamente.",
    status_text="success",
):
    return Response(
        {
            "data": data,
            "status": status_text,
            "message": message,
        },
        status=status_code,
    )


def api_error(
    data=None,
    status_code=status.HTTP_400_BAD_REQUEST,
    message="Ocurrió un error.",
):
    return Response(
        {
            "data": data,
            "status": "error",
            "message": message,
        },
        status=status_code,
    )

# from rest_framework.response import Response


# def api_response(data=None, status_code=200, message="Operación realizada correctamente.", status_text="success"):
#     return Response(
#         {
#             "data": data,
#             "status": status_text,
#             "message": message,
#         },
#         status=status_code,
#     )


# def api_error(data=None, status_code=400, message="Ocurrió un error."):
#     return Response(
#         {
#             "data": data,
#             "status": "error",
#             "message": message,
#         },
#         status=status_code,
#     )
