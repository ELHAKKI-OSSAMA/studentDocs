"""Catalog services: one small class per entity, sharing CrudService plumbing."""

import uuid

from sqlalchemy import or_, select

from app.academic.models import (
    AcademicYear,
    AcademicYearStatus,
    Branch,
    BranchCategory,
    DocumentType,
    StudyLevel,
    document_type_categories,
)
from app.academic.schemas import (
    AcademicYearIn,
    AcademicYearUpdate,
    BranchCategoryIn,
    BranchCategoryUpdate,
    BranchIn,
    BranchUpdate,
    DocumentTypeIn,
    DocumentTypeUpdate,
    StudyLevelIn,
    StudyLevelUpdate,
)
from app.core.crud import CrudService
from app.core.errors import AppError


def _dump(model) -> dict:
    return model.model_dump(mode="json", exclude_unset=True)


class AcademicYearService(CrudService[AcademicYear]):
    model = AcademicYear
    label = "Academic year"

    async def list_all(self, *, only_active: bool = False) -> list[AcademicYear]:
        stmt = select(AcademicYear).order_by(AcademicYear.start_date.desc())
        if only_active:
            stmt = stmt.where(AcademicYear.status == AcademicYearStatus.ACTIVE)
        return list((await self.db.scalars(stmt)).all())

    async def create(self, data: AcademicYearIn) -> AcademicYear:
        return await self.save(AcademicYear(**data.model_dump()))

    async def update(self, obj_id: uuid.UUID, data: AcademicYearUpdate) -> AcademicYear:
        year = await self.get(obj_id)
        self.apply(year, data.model_dump(exclude_unset=True, exclude_none=True))
        if year.end_date <= year.start_date:
            raise AppError.of(422, "invalid_dates", "end_date must be after start_date")
        return await self.save(year)


class BranchCategoryService(CrudService[BranchCategory]):
    model = BranchCategory
    label = "Category"

    async def list_all(self, *, only_active: bool = False) -> list[BranchCategory]:
        stmt = select(BranchCategory).order_by(BranchCategory.sort_order, BranchCategory.code)
        if only_active:
            stmt = stmt.where(BranchCategory.is_active.is_(True))
        return list((await self.db.scalars(stmt)).all())

    async def create(self, data: BranchCategoryIn) -> BranchCategory:
        return await self.save(BranchCategory(**_dump(data) | {"code": data.code}))

    async def update(self, obj_id: uuid.UUID, data: BranchCategoryUpdate) -> BranchCategory:
        category = await self.get(obj_id)
        self.apply(category, _dump(data))
        return await self.save(category)

    async def require(self, category_id: uuid.UUID) -> BranchCategory:
        category = await self.db.get(BranchCategory, category_id)
        if category is None:
            raise AppError.of(422, "invalid_reference", "Unknown category", {"field": "category_id"})
        return category


class BranchService(CrudService[Branch]):
    model = Branch
    label = "Branch"

    async def list_all(
        self, *, category_id: uuid.UUID | None = None, only_active: bool = False
    ) -> list[Branch]:
        stmt = select(Branch).join(Branch.category).order_by(BranchCategory.sort_order, Branch.code)
        if category_id:
            stmt = stmt.where(Branch.category_id == category_id)
        if only_active:
            stmt = stmt.where(Branch.is_active.is_(True), BranchCategory.is_active.is_(True))
        return list((await self.db.scalars(stmt)).unique().all())

    async def create(self, data: BranchIn) -> Branch:
        await BranchCategoryService(self.db).require(data.category_id)
        return await self.save(Branch(**_dump(data) | {"code": data.code, "category_id": data.category_id}))

    async def update(self, obj_id: uuid.UUID, data: BranchUpdate) -> Branch:
        branch = await self.get(obj_id)
        self.apply(branch, _dump(data))
        return await self.save(branch)


class StudyLevelService(CrudService[StudyLevel]):
    model = StudyLevel
    label = "Study level"

    async def list_all(
        self, *, category_id: uuid.UUID | None = None, only_active: bool = False
    ) -> list[StudyLevel]:
        stmt = (
            select(StudyLevel)
            .join(StudyLevel.category)
            .order_by(BranchCategory.sort_order, StudyLevel.sort_order)
        )
        if category_id:
            stmt = stmt.where(StudyLevel.category_id == category_id)
        if only_active:
            stmt = stmt.where(StudyLevel.is_active.is_(True), BranchCategory.is_active.is_(True))
        return list((await self.db.scalars(stmt)).unique().all())

    async def create(self, data: StudyLevelIn) -> StudyLevel:
        await BranchCategoryService(self.db).require(data.category_id)
        return await self.save(
            StudyLevel(**_dump(data) | {"code": data.code, "category_id": data.category_id})
        )

    async def update(self, obj_id: uuid.UUID, data: StudyLevelUpdate) -> StudyLevel:
        level = await self.get(obj_id)
        self.apply(level, _dump(data))
        return await self.save(level)


class DocumentTypeService(CrudService[DocumentType]):
    model = DocumentType
    label = "Document type"

    async def list_all(
        self, *, category_id: uuid.UUID | None = None, only_active: bool = False
    ) -> list[DocumentType]:
        stmt = select(DocumentType).order_by(DocumentType.code)
        if only_active:
            stmt = stmt.where(DocumentType.is_active.is_(True))
        if category_id:
            # No restriction rows = available to every category.
            restricted = select(document_type_categories.c.document_type_id).where(
                document_type_categories.c.document_type_id == DocumentType.id
            )
            allowed = select(document_type_categories.c.document_type_id).where(
                document_type_categories.c.document_type_id == DocumentType.id,
                document_type_categories.c.category_id == category_id,
            )
            stmt = stmt.where(or_(~restricted.exists(), allowed.exists()))
        return list((await self.db.scalars(stmt)).all())

    async def _categories(self, ids: list[uuid.UUID]) -> list[BranchCategory]:
        unique_ids = list(dict.fromkeys(ids))
        if not unique_ids:
            return []
        found = list(
            (await self.db.scalars(select(BranchCategory).where(BranchCategory.id.in_(unique_ids)))).all()
        )
        if len(found) != len(unique_ids):
            raise AppError.of(422, "invalid_reference", "Unknown category", {"field": "allowed_category_ids"})
        return found

    async def create(self, data: DocumentTypeIn) -> DocumentType:
        values = _dump(data)
        values.pop("allowed_category_ids", None)
        doc = DocumentType(**values | {"code": data.code})
        doc.allowed_categories = await self._categories(data.allowed_category_ids)
        return await self.save(doc)

    async def update(self, obj_id: uuid.UUID, data: DocumentTypeUpdate) -> DocumentType:
        doc = await self.get(obj_id)
        values = _dump(data)
        category_ids = values.pop("allowed_category_ids", None)
        self.apply(doc, values)
        if category_ids is not None:
            doc.allowed_categories = await self._categories(data.allowed_category_ids or [])
        return await self.save(doc)
