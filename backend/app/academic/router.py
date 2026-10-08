"""Catalog endpoints.

- /api/v1/catalog/*        : active entries, for any authenticated user holding `catalog.read`.
- /api/v1/admin/catalog/*  : full CRUD; read: `admin.access` + `catalog.read`;
                            write: `admin.access` + `catalog.manage`.
"""

import uuid

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.academic.schemas import (
    AcademicYearIn,
    AcademicYearOut,
    AcademicYearUpdate,
    BranchCategoryIn,
    BranchCategoryOut,
    BranchCategoryUpdate,
    BranchIn,
    BranchOut,
    BranchUpdate,
    DocumentTypeIn,
    DocumentTypeOut,
    DocumentTypeUpdate,
    StudyLevelIn,
    StudyLevelOut,
    StudyLevelUpdate,
)
from app.academic.services import (
    AcademicYearService,
    BranchCategoryService,
    BranchService,
    DocumentTypeService,
    StudyLevelService,
)
from app.auth.dependencies import Requires
from app.auth.permissions import Perm
from app.core.crud import CrudService
from app.core.deps import DbSession

AdminReader = Requires(Perm.ADMIN_ACCESS, Perm.CATALOG_READ)
CatalogManager = Requires(Perm.ADMIN_ACCESS, Perm.CATALOG_MANAGE)
CatalogReader = Requires(Perm.CATALOG_READ)

public_router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])
admin_router = APIRouter(prefix="/api/v1/admin/catalog", tags=["admin-catalog"])


def _register_crud(
    path: str,
    service_cls: type[CrudService],
    in_schema: type[BaseModel],
    update_schema: type[BaseModel],
    out_schema: type[BaseModel],
    *,
    filter_by_category: bool,
) -> None:
    """Registers list/get/create/update/delete admin routes for one catalog entity."""

    if filter_by_category:

        @admin_router.get(path, response_model=list[out_schema], name=f"admin_list_{path}")
        async def list_items(db: DbSession, _: AdminReader, category_id: uuid.UUID | None = None):
            return await service_cls(db).list_all(category_id=category_id)
    else:

        @admin_router.get(path, response_model=list[out_schema], name=f"admin_list_{path}")
        async def list_items(db: DbSession, _: AdminReader):
            return await service_cls(db).list_all()

    @admin_router.get(f"{path}/{{item_id}}", response_model=out_schema, name=f"admin_get_{path}")
    async def get_item(item_id: uuid.UUID, db: DbSession, _: AdminReader):
        return await service_cls(db).get(item_id)

    @admin_router.post(
        path, response_model=out_schema, status_code=status.HTTP_201_CREATED, name=f"admin_create_{path}"
    )
    async def create_item(data: in_schema, db: DbSession, _: CatalogManager):  # type: ignore[valid-type]
        return await service_cls(db).create(data)

    @admin_router.patch(f"{path}/{{item_id}}", response_model=out_schema, name=f"admin_update_{path}")
    async def update_item(item_id: uuid.UUID, data: update_schema, db: DbSession, _: CatalogManager):  # type: ignore[valid-type]
        return await service_cls(db).update(item_id, data)

    @admin_router.delete(
        f"{path}/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT, name=f"admin_delete_{path}"
    )
    async def delete_item(item_id: uuid.UUID, db: DbSession, _: CatalogManager) -> Response:
        await service_cls(db).delete(item_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


_register_crud(
    "/academic-years",
    AcademicYearService,
    AcademicYearIn,
    AcademicYearUpdate,
    AcademicYearOut,
    filter_by_category=False,
)
_register_crud(
    "/branch-categories",
    BranchCategoryService,
    BranchCategoryIn,
    BranchCategoryUpdate,
    BranchCategoryOut,
    filter_by_category=False,
)
_register_crud("/branches", BranchService, BranchIn, BranchUpdate, BranchOut, filter_by_category=True)
_register_crud(
    "/study-levels", StudyLevelService, StudyLevelIn, StudyLevelUpdate, StudyLevelOut, filter_by_category=True
)
_register_crud(
    "/document-types",
    DocumentTypeService,
    DocumentTypeIn,
    DocumentTypeUpdate,
    DocumentTypeOut,
    filter_by_category=True,
)


@public_router.get("/academic-years", response_model=list[AcademicYearOut])
async def active_years(db: DbSession, _: CatalogReader):
    return await AcademicYearService(db).list_all(only_active=True)


@public_router.get("/branch-categories", response_model=list[BranchCategoryOut])
async def active_categories(db: DbSession, _: CatalogReader):
    return await BranchCategoryService(db).list_all(only_active=True)


@public_router.get("/branches", response_model=list[BranchOut])
async def active_branches(db: DbSession, _: CatalogReader, category_id: uuid.UUID | None = None):
    return await BranchService(db).list_all(category_id=category_id, only_active=True)


@public_router.get("/study-levels", response_model=list[StudyLevelOut])
async def active_levels(db: DbSession, _: CatalogReader, category_id: uuid.UUID | None = None):
    return await StudyLevelService(db).list_all(category_id=category_id, only_active=True)


@public_router.get("/document-types", response_model=list[DocumentTypeOut])
async def active_document_types(db: DbSession, _: CatalogReader, category_id: uuid.UUID | None = None):
    return await DocumentTypeService(db).list_all(category_id=category_id, only_active=True)
